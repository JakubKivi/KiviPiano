from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Literal

from kivipiano.config import AppPaths
from kivipiano.fusion import (
    fuse_notes,
    read_notes_csv,
    write_fused_csv,
    write_fused_midi,
)
from kivipiano.media import download_youtube_audio, save_audio_for_later
from kivipiano.separation import separate_stem
from kivipiano.transcription import AMT_MODELS, transcribe_piano


SourceMode = Literal["file", "youtube"]
DownloadAudio = Callable[[str, Path], Path]
SaveAudio = Callable[[Path, Path], Path]
SeparateAudio = Callable[[str, str, str, str, str], Path]
TranscribeAudio = Callable[[str, str, str, str], tuple[Path, Path, int]]


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


@dataclass(frozen=True)
class ProcessingResult:
    message: str
    output_path: Path
    midi_path: Path
    selected_audio: Path | None = None


class AudioProcessingService:
    def __init__(
        self,
        paths: AppPaths,
        downloader: DownloadAudio | None = None,
        saver: SaveAudio | None = None,
        separator: SeparateAudio | None = None,
        transcriber: TranscribeAudio | None = None,
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

    def process(
        self,
        request: ProcessingRequest,
        on_progress: Callable[[str], None] | None = None,
    ) -> ProcessingResult:
        weights = self._validated_model_weights(request)

        def report(message: str) -> None:
            if on_progress is not None:
                on_progress(message)

        if request.source_mode == "youtube" and not request.save_for_later:
            with TemporaryDirectory(prefix="kivipiano-") as temp_dir:
                report("Downloading YouTube audio...")
                source_path = self._downloader(request.source, Path(temp_dir))
                report(
                    f"Separating the {request.stem} stem with "
                    f"{request.separator.title()}..."
                )
                output_path = self._separate(source_path, self.paths.output_dir, request)
        elif request.source_mode in {"file", "youtube"}:
            if request.source_mode == "youtube":
                report("Downloading YouTube audio...")
                source_path = self._downloader(request.source, self.paths.library_dir)
            else:
                source_path = Path(request.source).expanduser().resolve()
                if request.save_for_later:
                    report("Saving a copy to the library...")
                    source_path = self._saver(source_path, self.paths.library_dir)

            report(
                f"Separating the {request.stem} stem with "
                f"{request.separator.title()}..."
            )
            output_path = self._separate(
                source_path, source_path.parent / "KiviPiano_output", request
            )
        else:
            raise ValueError(f"Unknown audio source mode: {request.source_mode}")

        selected_audio = source_path if request.save_for_later else None
        notes_by_model: dict[str, list] = {}
        note_counts: dict[str, int] = {}
        for entry in request.amt_models:
            report(f"Transcribing with {AMT_MODELS[entry.name]}...")
            csv_path, _midi_path, note_count = self._transcriber(
                str(output_path),
                str(output_path.parent),
                str(self.paths.model_dir),
                entry.name,
            )
            notes_by_model[entry.name] = read_notes_csv(csv_path)
            note_counts[entry.name] = note_count

        report("Fusing notes...")
        fused_notes = fuse_notes(notes_by_model, weights)
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
