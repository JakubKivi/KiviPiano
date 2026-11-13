from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Literal

from kivipiano.config import AppPaths
from kivipiano.filters import FilterConfig, apply_filters
from kivipiano.fusion import (
    FusedNote,
    FusionConfig,
    fuse_notes,
    read_notes_csv,
    write_fused_csv,
    write_fused_midi,
)
from kivipiano.media import download_youtube_audio, save_audio_for_later
from kivipiano.musical_context import (
    BeatChordAnalysis,
    ContextConfig,
    analyze_musical_context,
    context_path,
    read_context,
    refine_notes,
)
from kivipiano.separation import expected_stem_path, separate_stem
from kivipiano.transcription import (
    AMT_MODELS,
    transcribe_piano,
    transcription_paths,
)


SourceMode = Literal["file", "youtube"]
DownloadAudio = Callable[[str, Path], Path]
SaveAudio = Callable[[Path, Path], Path]
SeparateAudio = Callable[[str, str, str, str, str], Path]
TranscribeAudio = Callable[[str, str, str, str], tuple[Path, Path, int]]
AnalyzeAudio = Callable[[str, str, str], BeatChordAnalysis]


@dataclass(frozen=True)
class ModelWeight:
    """A transcription model paired with its user-assigned fusion weight."""

    name: str
    weight: float


@dataclass(frozen=True)
class ProcessingRequest:
    source_mode: SourceMode
    source: str
    save_for_later: bool
    separator: str
    stem: str
    amt_models: tuple[ModelWeight, ...] = ()
    fusion: FusionConfig = field(default_factory=FusionConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)


@dataclass(frozen=True)
class ProcessingResult:
    message: str
    output_path: Path
    midi_path: Path
    selected_audio: Path | None = None
    raw_notes: tuple[FusedNote, ...] = ()


class AudioProcessingService:
    def __init__(
        self,
        paths: AppPaths,
        downloader: DownloadAudio | None = None,
        saver: SaveAudio | None = None,
        separator: SeparateAudio | None = None,
        transcriber: TranscribeAudio | None = None,
        analyzer: AnalyzeAudio | None = None,
    ) -> None:
        self.paths = paths
        self._downloader = (
            downloader if downloader is not None else download_youtube_audio
        )
        self._saver = saver if saver is not None else save_audio_for_later
        self._separator = separator if separator is not None else separate_stem
        self._transcriber = (
            transcriber if transcriber is not None else transcribe_piano
        )
        self._analyzer = (
            analyzer if analyzer is not None else analyze_musical_context
        )

    def process(
        self,
        request: ProcessingRequest,
        on_progress: Callable[[str], None] | None = None,
    ) -> ProcessingResult:
        request.fusion.validate()
        request.context.validate()
        request.filters.validate()
        weights = self._validated_model_weights(request)

        def report(message: str) -> None:
            if on_progress is not None:
                on_progress(message)

        if request.source_mode == "youtube" and not request.save_for_later:
            with TemporaryDirectory(prefix="kivipiano-") as temp_dir:
                report("Downloading YouTube audio...")
                source_path = self._downloader(request.source, Path(temp_dir))
                output_path = self._separate_reusing(
                    source_path, self.paths.output_dir, request, report
                )
        elif request.source_mode in {"file", "youtube"}:
            if request.source_mode == "youtube":
                report("Downloading YouTube audio...")
                source_path = self._downloader(request.source, self.paths.library_dir)
            else:
                source_path = Path(request.source).expanduser().resolve()
                if request.save_for_later:
                    report("Saving a copy to the library...")
                    source_path = self._saver(source_path, self.paths.library_dir)

            output_path = self._separate_reusing(
                source_path, source_path.parent / "KiviPiano_output", request, report
            )
        else:
            raise ValueError(f"Unknown audio source mode: {request.source_mode}")

        selected_audio = source_path if request.save_for_later else None
        notes_by_model: dict[str, list] = {}
        note_counts: dict[str, int] = {}
        for entry in request.amt_models:
            notes_by_model[entry.name], note_counts[entry.name] = (
                self._transcribe_reusing(output_path, entry.name, report)
            )

        report("Fusing notes...")
        raw_notes = fuse_notes(
            notes_by_model,
            weights,
            strategy=request.fusion.strategy,
            **request.fusion.strategy_kwargs(),
        )

        if request.context.enabled:
            report("Detecting beats and chords...")
            analysis = self._analyze_reusing(output_path, report)
            report("Refining notes against the beat/chord context...")
            raw_notes = refine_notes(raw_notes, analysis, request.context)

        report("Filtering notes...")
        fused_notes = apply_filters(raw_notes, request.filters)
        fused_csv = output_path.parent / f"{output_path.stem}_fused.csv"
        fused_midi = output_path.parent / f"{output_path.stem}_fused.mid"
        report("Writing fused MIDI and notes CSV...")
        write_fused_csv(fused_notes, fused_csv)
        write_fused_midi(fused_notes, fused_midi)

        model_summary = ", ".join(
            f"{AMT_MODELS[entry.name]} ({note_counts[entry.name]} notes)"
            for entry in request.amt_models
        )
        return ProcessingResult(
            message=(
                f"Done. Fused {len(fused_notes)} notes from {model_summary}.\n"
                f"MIDI: {fused_midi}\nNotes: {fused_csv}"
            ),
            output_path=fused_csv,
            midi_path=fused_midi,
            selected_audio=selected_audio,
            raw_notes=tuple(raw_notes),
        )

    def _validated_model_weights(self, request: ProcessingRequest) -> dict[str, float]:
        if not request.amt_models:
            raise ValueError("Select at least one transcription model.")
        weights: dict[str, float] = {}
        for entry in request.amt_models:
            if entry.name not in AMT_MODELS:
                raise ValueError(f"Unknown transcription model: {entry.name}")
            if (
                not isinstance(entry.weight, (int, float))
                or not isfinite(entry.weight)
                or entry.weight <= 0
            ):
                raise ValueError(
                    f"The weight for {entry.name} must be a positive number."
                )
            if entry.name in weights:
                raise ValueError(f"Duplicate transcription model: {entry.name}")
            weights[entry.name] = entry.weight
        return weights

    def _separate(
        self, source_path: Path, output_dir: Path, request: ProcessingRequest
    ) -> Path:
        return self._separator(
            str(source_path),
            str(output_dir),
            str(self.paths.model_dir),
            request.separator,
            request.stem,
        )

    def _separate_reusing(
        self,
        source_path: Path,
        output_dir: Path,
        request: ProcessingRequest,
        report: Callable[[str], None],
    ) -> Path:
        """Return the stem, reusing a previously separated one when present."""
        stem_path = expected_stem_path(
            source_path, output_dir, request.separator, request.stem
        )
        if stem_path.is_file():
            report(
                f"Reusing the existing {request.stem} stem "
                f"({request.separator.title()})."
            )
            return stem_path
        report(
            f"Separating the {request.stem} stem with "
            f"{request.separator.title()}..."
        )
        return self._separate(source_path, output_dir, request)

    def _transcribe_reusing(
        self, stem_path: Path, model_name: str, report: Callable[[str], None]
    ) -> tuple[list, int]:
        """Return ``(notes, note_count)``, reusing an existing transcription."""
        csv_path, midi_path = transcription_paths(
            stem_path, stem_path.parent, model_name
        )
        if midi_path.is_file() and csv_path.is_file():
            report(f"Reusing the existing {AMT_MODELS[model_name]} transcription.")
            notes = read_notes_csv(csv_path)
            return notes, len(notes)
        report(f"Transcribing with {AMT_MODELS[model_name]}...")
        csv_path, _midi_path, note_count = self._transcriber(
            str(stem_path),
            str(stem_path.parent),
            str(self.paths.model_dir),
            model_name,
        )
        return read_notes_csv(csv_path), note_count

    def _analyze_reusing(
        self, stem_path: Path, report: Callable[[str], None]
    ) -> BeatChordAnalysis:
        """Return the beat/chord analysis, reusing a previous one when present."""
        json_path = context_path(stem_path, stem_path.parent)
        if json_path.is_file():
            report("Reusing the existing beat/chord analysis.")
            return read_context(json_path)
        return self._analyzer(
            str(stem_path),
            str(stem_path.parent),
            str(self.paths.model_dir),
        )
