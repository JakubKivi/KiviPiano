"""Piano transcription backends and normalized note export."""

import csv
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Iterable, Protocol
from urllib.request import urlretrieve
import zipfile


AMT_MODELS = {
    "basic_pitch": "Spotify Basic Pitch",
    "magenta": "Google Magenta (Onsets & Frames)",
}
MAGENTA_CHECKPOINT_URL = (
    "https://storage.googleapis.com/magentadata/models/"
    "onsets_frames_transcription/maestro_checkpoint.zip"
)


class TranscribedNote(Protocol):
    start: float
    end: float
    pitch: int
    velocity: int


class TranscribedInstrument(Protocol):
    notes: list[TranscribedNote]


class MidiData(Protocol):
    instruments: list[TranscribedInstrument]

    def write(self, filename: str) -> None: ...


def transcribe_piano(
    audio_path: str,
    output_dir: str,
    model_dir: str,
    model_name: str = "basic_pitch",
) -> tuple[Path, Path, int]:
    source = Path(audio_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Separated piano audio does not exist: {source}")
    if model_name not in AMT_MODELS:
        raise ValueError(f"Unknown transcription model: {model_name}")

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    stem = f"{source.stem}_{model_name}"
    midi_path = destination / f"{stem}.mid"
    csv_path = destination / f"{stem}.csv"

    if model_name == "basic_pitch":
        midi_data = _predict_basic_pitch(source)
    else:
        midi_data = _predict_magenta(
            source, Path(model_dir).expanduser().resolve()
        )

    notes = [
        note
        for instrument in midi_data.instruments
        for note in instrument.notes
    ]
    midi_data.write(str(midi_path))
    _write_notes_csv(notes, csv_path, model_name)
    return csv_path, midi_path, len(notes)


def _predict_basic_pitch(audio_path: Path) -> MidiData:
    try:
        from basic_pitch.inference import predict
    except ImportError as exc:
        raise RuntimeError(
            "Spotify Basic Pitch is unavailable. Install the project requirements "
            "with `make install`."
        ) from exc

    _, midi_data, _ = predict(str(audio_path))
    return midi_data


def _predict_magenta(audio_path: Path, model_dir: Path) -> MidiData:
    try:
        import pretty_midi
    except ImportError as exc:
        raise RuntimeError(
            "pretty-midi is unavailable. Reinstall the project requirements."
        ) from exc

    executable = _magenta_executable()
    if executable is None:
        raise RuntimeError(
            "Google Magenta is not installed. Install Python 3.10 and run "
            "`make install-magenta`, then restart the application."
        )

    checkpoint_dir = _ensure_magenta_checkpoint(model_dir)
    with tempfile.TemporaryDirectory(prefix="kivipiano-magenta-") as temp_dir:
        temporary_audio = Path(temp_dir) / audio_path.name
        shutil.copy2(audio_path, temporary_audio)
        completed = subprocess.run(
            [
                str(executable),
                f"--model_dir={checkpoint_dir}",
                str(temporary_audio),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode:
            details = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(
                "Google Magenta transcription failed"
                + (f":\n{details[-2000:]}" if details else ".")
            )

        midi_path = temporary_audio.with_suffix(".midi")
        if not midi_path.is_file():
            raise RuntimeError(
                "Google Magenta finished without producing a MIDI transcription."
            )
        return pretty_midi.PrettyMIDI(str(midi_path))


def _magenta_executable() -> Path | None:
    configured = os.environ.get("KIVIPIANO_MAGENTA_EXECUTABLE")
    if configured:
        executable = Path(configured).expanduser()
        if executable.is_file():
            return executable.resolve()
        raise FileNotFoundError(
            "KIVIPIANO_MAGENTA_EXECUTABLE points to a missing file: "
            f"{executable}"
        )

    project_root = Path(__file__).resolve().parents[2]
    script_name = "onsets_frames_transcription_transcribe"
    if os.name == "nt":
        script_name += ".exe"
        local_executable = (
            project_root / ".venv-magenta" / "Scripts" / script_name
        )
    else:
        local_executable = (
            project_root / ".venv-magenta" / "bin" / script_name
        )
    if local_executable.is_file():
        return local_executable

    located = shutil.which(script_name)
    return Path(located) if located else None


def _ensure_magenta_checkpoint(model_dir: Path) -> Path:
    checkpoint_dir = model_dir / "magenta" / "maestro_checkpoint"
    if any(checkpoint_dir.glob("train/*.index")):
        return checkpoint_dir

    checkpoint_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="kivipiano-magenta-model-", dir=checkpoint_dir.parent
    ) as temp_dir:
        temp_root = Path(temp_dir)
        archive_path = temp_root / "checkpoint.zip"
        try:
            urlretrieve(MAGENTA_CHECKPOINT_URL, archive_path)
        except OSError as exc:
            raise RuntimeError(
                f"Could not download the Google Magenta checkpoint: {exc}"
            ) from exc

        extracted = temp_root / "extracted"
        extracted.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                target = (extracted / entry.filename).resolve()
                if not target.is_relative_to(extracted.resolve()):
                    raise RuntimeError(
                        "The Magenta checkpoint archive contains an invalid path."
                    )
                if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeError(
                        "The Magenta checkpoint archive contains a symbolic link."
                    )
            archive.extractall(extracted)

        checkpoint_files = list(extracted.rglob("*.index"))
        if not checkpoint_files:
            raise RuntimeError(
                "The downloaded Magenta checkpoint contains no TensorFlow "
                "checkpoint files."
            )
        source_dir = checkpoint_files[0].parent
        if checkpoint_dir.exists():
            raise RuntimeError(
                f"The Magenta checkpoint directory exists but is incomplete: "
                f"{checkpoint_dir}"
            )
        staged_dir = temp_root / "checkpoint"
        shutil.copytree(source_dir, staged_dir)
        staged_dir.replace(checkpoint_dir)

    if not any(checkpoint_dir.glob("*.index")):
        raise RuntimeError(
            "The Magenta checkpoint was downloaded, but its expected train "
            "checkpoint was not found."
        )
    return checkpoint_dir


def _write_notes_csv(
    notes: Iterable[TranscribedNote], csv_path: Path, model_name: str
) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(("start_time", "end_time", "pitch", "velocity", "model"))
        for note in sorted(
            notes, key=lambda item: (item.start, item.pitch, item.end)
        ):
            writer.writerow(
                (
                    f"{note.start:.6f}",
                    f"{note.end:.6f}",
                    note.pitch,
                    note.velocity,
                    model_name,
                )
            )
