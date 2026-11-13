"""Beat- and chord-aware note refinement for piano transcription.

After the per-model predictions are fused into one consensus set, the result
can still carry two subtle artifacts that the signal-level
:mod:`kivipiano.filters` cannot see:

* **false positives** — notes that are neither part of the harmony sounding at
  that moment nor aligned to the rhythmic grid (a stray transient, bleed, or a
  mistranscribed ghost), and
* **slight timing shifts** — chord notes whose onset lands a few milliseconds
  off the beat (models rarely place simultaneous chord attacks at exactly the
  same instant).

This stage runs between the AMT models and the note filters. It analyses the
separated piano stem with Madmom to recover the *beat grid* and the *chord
progression*, then refines the fused notes against that musical context:

* a note whose onset sits close to a beat is snapped onto it (fixing the
  slight shifts, and it keeps its duration), and
* a note that is both off the grid and outside the sounding chord is dropped
  as a likely false positive.

Like :mod:`kivipiano.fusion` and :mod:`kivipiano.filters`, the refinement logic
is pure Python and unit-testable without Madmom. The heavy lifting lives in
:func:`_run_madmom_analysis`, which is only reached inside the ``madmom``
Docker container (or on a host that happens to have Madmom installed).
"""

import json
import os
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Sequence

from kivipiano.docker_runtime import image_available, run_model_container
from kivipiano.fusion import FusedNote


_PITCH_CLASS_INDEX = {
    "C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4,
    "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
    "A#": 10, "BB": 10, "B": 11,
}
_MAJOR_INTERVALS = (0, 4, 7)
_MINOR_INTERVALS = (0, 3, 7)


@dataclass(frozen=True)
class ChordSegment:
    """One recognized chord covering ``[start, end)`` seconds."""

    start: float
    end: float
    label: str
    pitch_classes: frozenset[int]


@dataclass(frozen=True)
class BeatChordAnalysis:
    """The musical context extracted from a stem: its beats and chords."""

    beats: tuple[float, ...]
    tempo: float
    chords: tuple[ChordSegment, ...]


@dataclass(frozen=True)
class ContextConfig:
    """User-facing settings for the beat/chord refinement stage.

    ``enabled`` switches the whole stage on or off; the remaining fields tune
    the two sub-steps. ``validate`` rejects out-of-range values so the UI can
    surface problems before processing starts.
    """

    enabled: bool = False
    beat_snap: bool = True
    snap_tolerance: float = 0.05
    chord_filter: bool = True
    off_beat_tolerance: float = 0.05

    def validate(self) -> None:
        _require_positive("snap_tolerance", self.snap_tolerance)
        _require_positive("off_beat_tolerance", self.off_beat_tolerance)


def _require_positive(name: str, value: float) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number.")


def chord_pitch_classes(label: str) -> frozenset[int]:
    """Return the absolute pitch classes sounding in a Madmom chord label.

    Madmom writes labels such as ``"C:maj"``, ``"F#:min"``, or ``"N"`` for
    silence. ``"N"`` and any label this code does not understand yield an empty
    set, which callers treat as "no chord evidence" rather than "no chord".
    """
    if not label or ":" not in label:
        return frozenset()
    root_name, quality = label.split(":", 1)
    root = _PITCH_CLASS_INDEX.get(root_name.upper())
    if root is None:
        return frozenset()
    if quality == "maj":
        intervals = _MAJOR_INTERVALS
    elif quality == "min":
        intervals = _MINOR_INTERVALS
    else:
        return frozenset()
    return frozenset((root + interval) % 12 for interval in intervals)


def _nearest_beat(time: float, beats: Sequence[float]) -> tuple[float | None, float]:
    """Return ``(nearest_beat, distance)``, or ``(None, inf)`` with no beats."""
    if not beats:
        return None, float("inf")
    nearest = min(beats, key=lambda beat: abs(beat - time))
    return nearest, abs(nearest - time)


def _chord_pitch_classes_at(
    time: float, chords: Sequence[ChordSegment]
) -> frozenset[int] | None:
    """Return the pitch classes of the chord covering ``time``, if any.

    ``None`` means "no positive chord evidence": either no segment covers the
    time, or the segment is an explicit no-chord (``"N"``).
    """
    for chord in chords:
        if chord.start <= time < chord.end:
            return chord.pitch_classes or None
    return None


def refine_notes(
    notes: Sequence[FusedNote],
    analysis: BeatChordAnalysis,
    config: ContextConfig,
) -> list[FusedNote]:
    """Refine ``notes`` against ``analysis`` using the enabled sub-steps.

    * ``beat_snap`` moves an onset (and its end, keeping the duration) onto the
      nearest beat when it is within ``snap_tolerance``.
    * ``chord_filter`` drops a note only when it is *both* farther than
      ``off_beat_tolerance`` from a beat *and* not a member of the chord that
      sounds at that moment. Chord tones and on-grid notes (melody) are always
      kept, and missing beat/chord evidence never drops a note.
    """
    config.validate()
    if not notes:
        return []

    beats = analysis.beats
    chords = analysis.chords
    refined: list[FusedNote] = []
    for note in notes:
        start = note.start
        end = note.end
        nearest_beat, beat_distance = _nearest_beat(start, beats)

        if (
            config.beat_snap
            and nearest_beat is not None
            and beat_distance <= config.snap_tolerance
        ):
            delta = nearest_beat - start
            start = nearest_beat
            end = max(nearest_beat, end + delta)

        if config.chord_filter and nearest_beat is not None and chords:
            off_beat = beat_distance > config.off_beat_tolerance
            sounding = _chord_pitch_classes_at(start, chords)
            if off_beat and sounding is not None and note.pitch % 12 not in sounding:
                continue

        if start != note.start or end != note.end:
            refined.append(
                FusedNote(
                    start, end, note.pitch, note.velocity, note.confidence, note.models
                )
            )
        else:
            refined.append(note)

    return sorted(refined, key=lambda item: (item.start, item.pitch, item.end))


def context_path(audio_path: str | Path, output_dir: str | Path) -> Path:
    """Return the deterministic ``*.json`` path for a stem's beat/chord data."""
    source = Path(audio_path).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    return destination / f"{source.stem}_context.json"


def context_available() -> bool:
    """Return whether the Madmom analysis image is built locally."""
    return image_available("madmom")


def write_context(analysis: BeatChordAnalysis, json_path: str | Path) -> None:
    """Write ``analysis`` as the JSON consumed by :func:`read_context`."""
    payload = {
        "beats": [float(beat) for beat in analysis.beats],
        "tempo": float(analysis.tempo),
        "chords": [
            {"start": float(chord.start), "end": float(chord.end), "label": chord.label}
            for chord in analysis.chords
        ],
    }
    with Path(json_path).open("w", encoding="utf-8") as json_file:
        json.dump(payload, json_file, indent=2)


def read_context(json_path: str | Path) -> BeatChordAnalysis:
    """Read a beat/chord analysis produced by :func:`write_context`."""
    path = Path(json_path)
    if not path.is_file():
        raise FileNotFoundError(f"Beat/chord analysis does not exist: {path}")
    with path.open(encoding="utf-8") as json_file:
        data = json.load(json_file)
    beats = tuple(float(beat) for beat in data.get("beats", []))
    tempo = float(data.get("tempo", 0.0))
    chords = tuple(
        ChordSegment(
            float(chord["start"]),
            float(chord["end"]),
            str(chord["label"]),
            chord_pitch_classes(str(chord["label"])),
        )
        for chord in data.get("chords", [])
    )
    return BeatChordAnalysis(beats, tempo, chords)


def _tempo_from_beats(beats: Sequence[float]) -> float:
    """Estimate BPM as ``60 / median(inter-beat interval)``."""
    if len(beats) < 2:
        return 0.0
    intervals = [
        second - first
        for first, second in zip(beats, beats[1:])
        if second > first
    ]
    if not intervals:
        return 0.0
    median = sorted(intervals)[len(intervals) // 2]
    return 60.0 / median if median > 0 else 0.0


def _run_madmom_analysis(
    audio_path: str | Path, json_path: str | Path
) -> BeatChordAnalysis:
    """Run Madmom beat tracking and chord recognition, then persist the result.

    Only reached inside the ``madmom`` container (or a host with Madmom), so the
    Madmom import is deliberately lazy.
    """
    try:
        import numpy as np
        from madmom.features.beats import DBNBeatTrackingProcessor, RNNBeatProcessor
        from madmom.features.chords import (
            CNNChordFeatureProcessor,
            CRFChordRecognitionProcessor,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Madmom is unavailable in its container image. Run `make install`."
        ) from exc

    audio = str(audio_path)

    beat_activations = RNNBeatProcessor()(audio)
    beat_array = np.asarray(DBNBeatTrackingProcessor(fps=100)(beat_activations))
    beat_times = [float(t) for t in beat_array[:, 0]] if beat_array.size else []
    tempo = _tempo_from_beats(beat_times)

    chord_features = CNNChordFeatureProcessor()(audio)
    chord_rows = CRFChordRecognitionProcessor()(chord_features)
    chords = tuple(
        ChordSegment(
            float(row["start"]),
            float(row["end"]),
            str(row["label"]),
            chord_pitch_classes(str(row["label"])),
        )
        for row in chord_rows
    )

    analysis = BeatChordAnalysis(tuple(beat_times), tempo, chords)
    write_context(analysis, json_path)
    return analysis


def analyze_musical_context(
    audio_path: str,
    output_dir: str,
    model_dir: str,
) -> BeatChordAnalysis:
    """Analyse a stem's beats and chords.

    On the host this delegates to the ``madmom`` container and reads its JSON
    back; inside the container (``KIVIPIANO_CONTAINER_WORKER=1``) it performs
    the Madmom work directly and returns the analysis.
    """
    source = Path(audio_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Separated piano audio does not exist: {source}")

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    json_path = context_path(source, destination)

    if os.environ.get("KIVIPIANO_CONTAINER_WORKER") != "1":
        run_model_container("madmom", "analyze", model_dir, source, destination)
        if not json_path.is_file():
            raise RuntimeError(
                "The Madmom container finished without producing a context file."
            )
        return read_context(json_path)

    return _run_madmom_analysis(source, json_path)
