"""Weighted multi-model note fusion for piano transcription.

The application transcribes the separated piano stem with one or more AMT
models and then combines their note predictions into a single consensus note
set. This module implements that combination step.

It is deliberately model-agnostic: it only consumes the normalized note CSV
each model already writes (``start_time``, ``end_time``, ``pitch``,
``velocity``, ``model``), so adding a new transcription model requires no
changes here. The new model's CSV is simply included in the fusion inputs.
"""

import csv
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Callable, Iterable, Protocol, Sequence


@dataclass(frozen=True)
class Note:
    """A single normalized note prediction produced by one model."""

    start: float
    end: float
    pitch: int
    velocity: int
    model: str


@dataclass(frozen=True)
class FusedNote:
    """An aggregated note produced by fusing several model predictions."""

    start: float
    end: float
    pitch: int
    velocity: int
    confidence: float
    models: tuple[str, ...]


@dataclass(frozen=True)
class ModelPrediction:
    """One model's note predictions together with its fusion weight."""

    name: str
    weight: float
    notes: tuple[Note, ...]


def _validate_fraction(name: str, value: float) -> None:
    """Raise unless ``value`` is a finite number in the ``[0, 1]`` range."""
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be a number between 0 and 1.")


@dataclass(frozen=True)
class FusionConfig:
    """User-facing settings that control how per-model notes are fused.

    The defaults mirror :class:`WeightedVoteFusion`. ``validate`` rejects
    out-of-range values so the UI can surface problems before processing starts,
    and ``strategy_kwargs`` maps the fields onto the strategy constructor.
    """

    strategy: str = "weighted_vote"
    overlap_threshold: float = 0.25
    min_confidence: float = 0.0

    def validate(self) -> None:
        if self.strategy not in FUSION_STRATEGIES:
            raise ValueError(f"Unknown fusion strategy: {self.strategy}")
        _validate_fraction("overlap_threshold", self.overlap_threshold)
        _validate_fraction("min_confidence", self.min_confidence)

    def strategy_kwargs(self) -> dict[str, float]:
        """Return the keyword arguments for the configured strategy."""
        self.validate()
        return {
            "overlap_threshold": self.overlap_threshold,
            "min_confidence": self.min_confidence,
        }


class FusionStrategy(Protocol):
    """Combines per-model note predictions into one consensus note set.

    Implementations receive model predictions with their user-assigned weights
    and return a list of fused notes. Add a new strategy by implementing this
    protocol and registering it in :data:`FUSION_STRATEGIES`.
    """

    def fuse(self, predictions: Sequence[ModelPrediction]) -> list[FusedNote]:
        ...


def _normalize_weights(
    predictions: Sequence[ModelPrediction],
) -> dict[str, float]:
    """Return model weights scaled so their total is ``1``."""
    total = 0.0
    for prediction in predictions:
        if not isfinite(prediction.weight) or prediction.weight < 0:
            raise ValueError(
                f"The weight for {prediction.name} must be a non-negative number."
            )
        total += prediction.weight
    if total <= 0:
        raise ValueError("At least one model with a positive weight is required.")
    return {prediction.name: prediction.weight / total for prediction in predictions}


def _notes_match(first: Note, other: Note, overlap_threshold: float) -> bool:
    """Return whether two notes describe the same musical event.

    Notes match when they share a pitch and their temporal overlap covers at
    least ``overlap_threshold`` of the shorter note.
    """
    if first.pitch != other.pitch:
        return False
    overlap = min(first.end, other.end) - max(first.start, other.start)
    if overlap <= 0:
        return False
    shorter = min(first.end - first.start, other.end - other.start)
    if shorter <= 0:
        return False
    return overlap / shorter >= overlap_threshold


def _cluster_notes(
    predictions: Sequence[ModelPrediction], overlap_threshold: float
) -> list[list[Note]]:
    """Greedily group matching notes into clusters.

    Notes are processed in onset order; each note joins the first cluster whose
    earliest note it matches, or starts a new cluster otherwise.
    """
    notes = [note for prediction in predictions for note in prediction.notes]
    notes.sort(key=lambda note: (note.start, note.pitch, note.end))
    clusters: list[list[Note]] = []
    for note in notes:
        for cluster in clusters:
            if _notes_match(cluster[0], note, overlap_threshold):
                cluster.append(note)
                break
        else:
            clusters.append([note])
    return clusters


def _aggregate_cluster(
    cluster: list[Note], weights: dict[str, float]
) -> FusedNote:
    """Combine the notes in a cluster into one weighted-average note."""
    by_model: dict[str, list[Note]] = {}
    for note in cluster:
        by_model.setdefault(note.model, []).append(note)

    summaries: dict[str, dict[str, float]] = {}
    for model, model_notes in by_model.items():
        count = len(model_notes)
        summaries[model] = {
            "start": sum(note.start for note in model_notes) / count,
            "end": sum(note.end for note in model_notes) / count,
            "velocity": sum(note.velocity for note in model_notes) / count,
        }

    total_weight = sum(weights[model] for model in summaries)
    start = sum(
        summaries[model]["start"] * weights[model] for model in summaries
    ) / total_weight
    end = sum(
        summaries[model]["end"] * weights[model] for model in summaries
    ) / total_weight
    velocity = round(
        sum(
            summaries[model]["velocity"] * weights[model] for model in summaries
        )
        / total_weight
    )
    return FusedNote(
        start=start,
        end=end,
        pitch=cluster[0].pitch,
        velocity=velocity,
        confidence=total_weight,
        models=tuple(sorted(summaries)),
    )


class WeightedVoteFusion:
    """Default fusion strategy: weighted vote over clustered notes.

    Notes that share a pitch and overlap enough in time are treated as the same
    musical event. Each cluster becomes one note whose onset, offset, and
    velocity are weighted averages (using the model weights) and whose
    confidence is the summed normalized weight of the contributing models.
    Clusters whose confidence is below ``min_confidence`` are dropped.
    """

    def __init__(
        self, overlap_threshold: float = 0.25, min_confidence: float = 0.0
    ) -> None:
        _validate_fraction("overlap_threshold", overlap_threshold)
        _validate_fraction("min_confidence", min_confidence)
        self.overlap_threshold = overlap_threshold
        self.min_confidence = min_confidence

    def fuse(self, predictions: Sequence[ModelPrediction]) -> list[FusedNote]:
        weights = _normalize_weights(predictions)
        clusters = _cluster_notes(predictions, self.overlap_threshold)
        fused = [_aggregate_cluster(cluster, weights) for cluster in clusters]
        fused = [note for note in fused if note.confidence >= self.min_confidence]
        return sorted(fused, key=lambda note: (note.start, note.pitch, note.end))


FUSION_STRATEGIES: dict[str, Callable[..., FusionStrategy]] = {
    "weighted_vote": WeightedVoteFusion,
}


def create_fusion_strategy(name: str, **kwargs) -> FusionStrategy:
    """Instantiate a registered fusion strategy by name."""
    try:
        factory = FUSION_STRATEGIES[name]
    except KeyError:
        raise ValueError(f"Unknown fusion strategy: {name}") from None
    return factory(**kwargs)


def fuse_notes(
    notes_by_model: dict[str, Sequence[Note]],
    weights: dict[str, float],
    *,
    strategy: str = "weighted_vote",
    **strategy_kwargs,
) -> list[FusedNote]:
    """Fuse per-model notes into a consensus note set.

    ``notes_by_model`` maps a model name to its note predictions and ``weights``
    maps the same names to their user-assigned fusion weights (any positive
    scale; they are normalized internally).
    """
    predictions = [
        ModelPrediction(
            name=name,
            weight=float(weights.get(name, 0.0)),
            notes=tuple(notes),
        )
        for name, notes in notes_by_model.items()
    ]
    return create_fusion_strategy(strategy, **strategy_kwargs).fuse(predictions)


def read_notes_csv(csv_path: str | Path) -> list[Note]:
    """Read a model's normalized note CSV into :class:`Note` objects."""
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Transcription CSV does not exist: {path}")
    notes: list[Note] = []
    with path.open(encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            notes.append(
                Note(
                    start=float(row["start_time"]),
                    end=float(row["end_time"]),
                    pitch=int(row["pitch"]),
                    velocity=int(row["velocity"]),
                    model=row["model"],
                )
            )
    return notes


def read_fused_csv(csv_path: str | Path) -> list[FusedNote]:
    """Read the fused transcription CSV into :class:`FusedNote` objects."""
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Fused transcription CSV does not exist: {path}")
    notes: list[FusedNote] = []
    with path.open(encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            notes.append(
                FusedNote(
                    start=float(row["start_time"]),
                    end=float(row["end_time"]),
                    pitch=int(row["pitch"]),
                    velocity=int(row["velocity"]),
                    confidence=float(row["confidence"]),
                    models=tuple(row["models"].split(";")),
                )
            )
    return notes


def write_fused_csv(notes: Iterable[FusedNote], csv_path: str | Path) -> None:
    """Write fused notes to a CSV that also records confidence and sources."""
    path = Path(csv_path)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            ("start_time", "end_time", "pitch", "velocity", "confidence", "models")
        )
        for note in notes:
            writer.writerow(
                (
                    f"{note.start:.6f}",
                    f"{note.end:.6f}",
                    note.pitch,
                    note.velocity,
                    f"{note.confidence:.6f}",
                    ";".join(note.models),
                )
            )


def write_fused_midi(notes: Iterable[FusedNote], midi_path: str | Path) -> None:
    """Write fused notes to a MIDI file."""
    try:
        import pretty_midi
    except ImportError as exc:
        raise RuntimeError(
            "pretty-midi is unavailable. Reinstall the project requirements."
        ) from exc

    midi = pretty_midi.PrettyMIDI()
    instrument = pretty_midi.Instrument(program=0)
    for note in notes:
        instrument.notes.append(
            pretty_midi.Note(
                velocity=max(0, min(127, note.velocity)),
                pitch=max(0, min(127, note.pitch)),
                start=note.start,
                end=max(note.start, note.end),
            )
        )
    midi.instruments.append(instrument)
    midi.write(str(midi_path))
