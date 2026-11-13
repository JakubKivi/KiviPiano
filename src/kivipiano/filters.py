"""Post-fusion note filtering for piano transcription.

After fusing the per-model note predictions into one consensus set, the result
can still contain common artifacts: percussion transients and vocal sibilants
(notes of a few milliseconds), quiet vocal bleed left over from separation,
cymbal bleed in the highest octaves and bass rumble at the bottom, one long
note chopped into a burst of short "machine gun" hits, a "cloud" of
simultaneous notes during a loud chorus, and ghost notes an octave (12
semitones) or an octave-plus-fifth (19 semitones) above a real note.

This module cleans those up with a pipeline of independent, composable
:class:`NoteFilter` implementations. Each filter is registered in
:data:`NOTE_FILTERS` and enabled/tuned through :class:`FilterConfig`, so
filters are easy to switch on or off, adjust, and extend.

To add a new filter:
1. implement the :class:`NoteFilter` protocol (``apply(notes) -> notes``),
2. register its constructor in :data:`NOTE_FILTERS`,
3. add its name to :data:`FILTER_ORDER`,
4. add an enable flag and parameters to :class:`FilterConfig` (and validate
   them), then pass their keyword arguments in :func:`_enabled_filters`.
"""

from dataclasses import dataclass
from math import floor, isfinite
from typing import Callable, Protocol, Sequence

from kivipiano.fusion import FusedNote


class NoteFilter(Protocol):
    """Transforms a list of fused notes (dropping or merging notes)."""

    def apply(self, notes: list[FusedNote]) -> list[FusedNote]:
        ...


def _require_positive(name: str, value: float) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number.")


def _require_fraction(name: str, value: float) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be a number between 0 and 1.")


def _require_percent(name: str, value: float) -> None:
    if not isfinite(value) or not 0.0 <= value <= 100.0:
        raise ValueError(f"{name} must be a number between 0 and 100.")


def _percentile(values: Sequence[int], percentile: float) -> float:
    """Return the linearly interpolated ``percentile`` of ``values``."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


class DurationGate:
    """Drop notes shorter than ``min_duration`` seconds."""

    def __init__(self, min_duration: float = 0.05) -> None:
        _require_positive("min_duration", min_duration)
        self.min_duration = min_duration

    def apply(self, notes: list[FusedNote]) -> list[FusedNote]:
        return [
            note for note in notes if note.end - note.start >= self.min_duration
        ]


class VelocityGate:
    """Drop notes quieter than the piece's ``percentile`` velocity.

    The threshold adapts to the piece instead of using a fixed MIDI velocity,
    so quiet vocal bleed is removed while a uniformly soft performance is kept.
    """

    def __init__(self, percentile: float = 20.0) -> None:
        _require_percent("percentile", percentile)
        self.percentile = percentile

    def apply(self, notes: list[FusedNote]) -> list[FusedNote]:
        if not notes:
            return []
        threshold = _percentile([note.velocity for note in notes], self.percentile)
        return [note for note in notes if note.velocity >= threshold]


class PitchBandPass:
    """Keep only notes whose MIDI pitch is within ``[min_pitch, max_pitch]``."""

    def __init__(self, min_pitch: int = 28, max_pitch: int = 96) -> None:
        if not isinstance(min_pitch, int) or not isinstance(max_pitch, int):
            raise ValueError("min_pitch and max_pitch must be integers.")
        if min_pitch > max_pitch:
            raise ValueError("min_pitch must not exceed max_pitch.")
        self.min_pitch = min_pitch
        self.max_pitch = max_pitch

    def apply(self, notes: list[FusedNote]) -> list[FusedNote]:
        return [
            note
            for note in notes
            if self.min_pitch <= note.pitch <= self.max_pitch
        ]


def _merge_pair(first: FusedNote, second: FusedNote) -> FusedNote:
    """Combine two same-pitch notes into one longer note."""
    return FusedNote(
        start=first.start,
        end=max(first.end, second.end),
        pitch=first.pitch,
        velocity=max(first.velocity, second.velocity),
        confidence=max(first.confidence, second.confidence),
        models=tuple(sorted(set(first.models) | set(second.models))),
    )


class NoteMerger:
    """Stitch same-pitch notes separated by a gap smaller than ``max_gap``.

    Models often cut one long note into a burst of short "machine gun" hits of
    the same key. Notes that share a pitch and are separated by a gap smaller
    than ``max_gap`` seconds are joined into a single note.
    """

    def __init__(self, max_gap: float = 0.04) -> None:
        _require_positive("max_gap", max_gap)
        self.max_gap = max_gap

    def apply(self, notes: list[FusedNote]) -> list[FusedNote]:
        by_pitch: dict[int, list[FusedNote]] = {}
        for note in notes:
            by_pitch.setdefault(note.pitch, []).append(note)

        merged: list[FusedNote] = []
        for pitch in sorted(by_pitch):
            group = sorted(by_pitch[pitch], key=lambda note: note.start)
            current = group[0]
            for note in group[1:]:
                if note.start - current.end < self.max_gap:
                    current = _merge_pair(current, note)
                else:
                    merged.append(current)
                    current = note
            merged.append(current)

        return sorted(merged, key=lambda note: (note.start, note.pitch, note.end))


class PolyphonyLimiter:
    """Keep only the loudest ``max_notes`` notes in each time ``window``.

    When a loud chorus confuses the model it can report a dozen simultaneous
    notes. Bucketing the timeline into small windows and keeping only the
    loudest few notes in each window caps that polyphony.
    """

    def __init__(self, window: float = 0.05, max_notes: int = 5) -> None:
        _require_positive("window", window)
        if not isinstance(max_notes, int) or max_notes < 1:
            raise ValueError("max_notes must be a positive integer.")
        self.window = window
        self.max_notes = max_notes

    def apply(self, notes: list[FusedNote]) -> list[FusedNote]:
        if not notes:
            return []
        ordered = sorted(notes, key=lambda note: note.start)
        origin = ordered[0].start
        windows: dict[int, list[FusedNote]] = {}
        for note in ordered:
            index = floor((note.start - origin) / self.window)
            windows.setdefault(index, []).append(note)

        kept: list[FusedNote] = []
        for index in sorted(windows):
            window_notes = sorted(
                windows[index], key=lambda note: (-note.velocity, note.pitch)
            )
            kept.extend(window_notes[: self.max_notes])
        return sorted(kept, key=lambda note: (note.start, note.pitch, note.end))


class OvertoneSuppressor:
    """Drop a quiet note 12/19 semitones above a louder overlapping note.

    Striking a key excites an octave (12 semitones) and an octave-plus-fifth
    (19 semitones) above it. If two overlapping notes are separated by exactly
    one of those intervals and the upper note is no louder than ``ratio`` times
    the lower one, the upper note is almost certainly a ghost overtone and is
    removed.
    """

    DEFAULT_INTERVALS = (12, 19)

    def __init__(
        self,
        ratio: float = 0.5,
        intervals: Sequence[int] = DEFAULT_INTERVALS,
    ) -> None:
        _require_fraction("ratio", ratio)
        self.ratio = ratio
        self.intervals = tuple(intervals)

    def apply(self, notes: list[FusedNote]) -> list[FusedNote]:
        ordered = sorted(notes, key=lambda note: note.start)
        suppressed: set[int] = set()
        for index, first in enumerate(ordered):
            for other_index in range(index + 1, len(ordered)):
                second = ordered[other_index]
                if second.start >= first.end:
                    break
                if first.pitch < second.pitch:
                    lower, upper = first, second
                    upper_index = other_index
                else:
                    lower, upper = second, first
                    upper_index = index
                interval = upper.pitch - lower.pitch
                if (
                    interval in self.intervals
                    and upper.velocity <= lower.velocity * self.ratio
                ):
                    suppressed.add(upper_index)

        return [
            note for index, note in enumerate(ordered) if index not in suppressed
        ]


NOTE_FILTERS: dict[str, Callable[..., NoteFilter]] = {
    "duration_gate": DurationGate,
    "velocity_gate": VelocityGate,
    "pitch_band_pass": PitchBandPass,
    "merge_notes": NoteMerger,
    "polyphony_limit": PolyphonyLimiter,
    "overtone_suppression": OvertoneSuppressor,
}

#: Order in which enabled filters run. Merging runs before the duration gate so
#: short fragments are stitched together instead of being dropped as artifacts.
FILTER_ORDER: tuple[str, ...] = (
    "pitch_band_pass",
    "overtone_suppression",
    "merge_notes",
    "duration_gate",
    "velocity_gate",
    "polyphony_limit",
)


def create_note_filter(name: str, **kwargs) -> NoteFilter:
    """Instantiate a registered note filter by name."""
    try:
        factory = NOTE_FILTERS[name]
    except KeyError:
        raise ValueError(f"Unknown note filter: {name}") from None
    return factory(**kwargs)


@dataclass(frozen=True)
class FilterConfig:
    """User-facing settings for the post-fusion note filters.

    Each boolean field switches its filter on or off; the remaining fields tune
    the enabled filters. ``validate`` rejects out-of-range values so the UI can
    surface problems before processing starts.
    """

    duration_gate: bool = True
    min_duration: float = 0.05

    velocity_gate: bool = True
    velocity_percentile: float = 20.0

    pitch_band_pass: bool = True
    min_pitch: int = 28
    max_pitch: int = 96

    merge_notes: bool = True
    merge_gap: float = 0.04

    polyphony_limit: bool = True
    polyphony_window: float = 0.05
    polyphony_max: int = 5

    overtone_suppression: bool = True
    overtone_ratio: float = 0.5

    def validate(self) -> None:
        _require_positive("min_duration", self.min_duration)
        _require_percent("velocity_percentile", self.velocity_percentile)
        if not isinstance(self.min_pitch, int) or not isinstance(self.max_pitch, int):
            raise ValueError("min_pitch and max_pitch must be integers.")
        if self.min_pitch > self.max_pitch:
            raise ValueError("min_pitch must not exceed max_pitch.")
        _require_positive("merge_gap", self.merge_gap)
        _require_positive("polyphony_window", self.polyphony_window)
        if not isinstance(self.polyphony_max, int) or self.polyphony_max < 1:
            raise ValueError("polyphony_max must be a positive integer.")
        _require_fraction("overtone_ratio", self.overtone_ratio)


class FilterPipeline:
    """Applies a sequence of note filters in order."""

    def __init__(self, filters: Sequence[NoteFilter]) -> None:
        self._filters = list(filters)

    def apply(self, notes: list[FusedNote]) -> list[FusedNote]:
        for note_filter in self._filters:
            notes = note_filter.apply(notes)
        return notes


def _enabled_filters(config: FilterConfig) -> list[NoteFilter]:
    """Build the enabled filters from ``config`` in ``FILTER_ORDER`` order."""
    kwargs_by_name = {
        "pitch_band_pass": {
            "min_pitch": config.min_pitch,
            "max_pitch": config.max_pitch,
        },
        "overtone_suppression": {"ratio": config.overtone_ratio},
        "merge_notes": {"max_gap": config.merge_gap},
        "duration_gate": {"min_duration": config.min_duration},
        "velocity_gate": {"percentile": config.velocity_percentile},
        "polyphony_limit": {
            "window": config.polyphony_window,
            "max_notes": config.polyphony_max,
        },
    }
    filters: list[NoteFilter] = []
    for name in FILTER_ORDER:
        if getattr(config, name):
            filters.append(create_note_filter(name, **kwargs_by_name[name]))
    return filters


def build_filter_pipeline(config: FilterConfig) -> FilterPipeline:
    """Return a pipeline built from the enabled filters in ``config``."""
    config.validate()
    return FilterPipeline(_enabled_filters(config))


def apply_filters(
    notes: Sequence[FusedNote], config: FilterConfig
) -> list[FusedNote]:
    """Filter ``notes`` through the enabled filters in ``config``."""
    return build_filter_pipeline(config).apply(list(notes))
