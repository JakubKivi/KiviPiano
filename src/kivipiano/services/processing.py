from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Literal

from kivipiano.config import AppPaths
from kivipiano.media import download_youtube_audio, save_audio_for_later
from kivipiano.separation import separate_stem
from kivipiano.transcription import AMT_MODELS, transcribe_piano


SourceMode = Literal["file", "youtube"]
DownloadAudio = Callable[[str, Path], Path]
SaveAudio = Callable[[Path, Path], Path]
SeparateAudio = Callable[[str, str, str, str, str], Path]
TranscribeAudio = Callable[[str, str, str, str], tuple[Path, Path, int]]


@dataclass(frozen=True)
class ProcessingRequest:
    source_mode: SourceMode
    source: str
    save_for_later: bool
    separator: str
    stem: str
    amt_model: str = "basic_pitch"


@dataclass(frozen=True)
class ProcessingResult:
    message: str
    output_path: Path
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

    def process(self, request: ProcessingRequest) -> ProcessingResult:
        if request.amt_model not in AMT_MODELS:
            raise ValueError(f"Unknown transcription model: {request.amt_model}")

        if request.source_mode == "youtube" and not request.save_for_later:
            with TemporaryDirectory(prefix="kivipiano-") as temp_dir:
                source_path = self._downloader(request.source, Path(temp_dir))
                output_path = self._separate(source_path, self.paths.output_dir, request)
        elif request.source_mode in {"file", "youtube"}:
            if request.source_mode == "youtube":
                source_path = self._downloader(request.source, self.paths.library_dir)
            else:
                source_path = Path(request.source).expanduser().resolve()
                if request.save_for_later:
                    source_path = self._saver(source_path, self.paths.library_dir)

            output_path = self._separate(
                source_path, source_path.parent / "KiviPiano_output", request
            )
        else:
            raise ValueError(f"Unknown audio source mode: {request.source_mode}")

        selected_audio = source_path if request.save_for_later else None
        csv_path, midi_path, note_count = self._transcriber(
            str(output_path),
            str(output_path.parent),
            str(self.paths.model_dir),
            request.amt_model,
        )
        return ProcessingResult(
            message=(
                f"Done. {AMT_MODELS[request.amt_model]} transcribed "
                f"{note_count} notes.\nMIDI: {midi_path}\nNotes: {csv_path}"
            ),
            output_path=csv_path,
            selected_audio=selected_audio,
        )

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
