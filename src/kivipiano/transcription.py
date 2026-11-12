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

from kivipiano.docker_runtime import image_available, run_model_container


AMT_MODELS = {
    "basic_pitch": "Spotify Basic Pitch",
    "magenta": "Google Magenta (Onsets & Frames)",
    "bytedance": "ByteDance Piano Transcription",
    "omnizart": "Omnizart",
}


def basic_pitch_available() -> bool:
    """Return whether the Basic Pitch image is built."""
    return image_available("basic_pitch")


def magenta_available(model_dir: Path) -> bool:
    """Return whether Google Magenta is ready to use (runtime + checkpoint)."""
    return (
        image_available("magenta")
        and _has_magenta_checkpoint(magenta_checkpoint_dir(model_dir))
    )


def amt_model_available(model_name: str, model_dir: Path) -> bool:
    """Return whether a transcription image and its model files are installed."""
    model_path = Path(model_dir).expanduser().resolve()
    if model_name == "basic_pitch":
        return basic_pitch_available()
    if model_name == "magenta":
        return magenta_available(model_path)
    if model_name == "bytedance":
        checkpoint = model_path / "bytedance" / "piano_transcription.pth"
        return image_available(model_name) and checkpoint.is_file()
    if model_name == "omnizart":
        marker = model_path / "omnizart" / ".checkpoints-ready"
        return image_available(model_name) and marker.is_file()
    raise ValueError(f"Unknown transcription model: {model_name}")


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

    if os.environ.get("KIVIPIANO_CONTAINER_WORKER") != "1":
        run_model_container(
            model_name,
            "transcribe",
            Path(model_dir).expanduser().resolve(),
            source,
            destination,
        )
        if not midi_path.is_file() or not csv_path.is_file():
            raise RuntimeError(
                f"The {AMT_MODELS[model_name]} container finished without "
                "producing its MIDI and CSV files."
            )
        with csv_path.open(encoding="utf-8", newline="") as csv_file:
            note_count = sum(1 for _ in csv.DictReader(csv_file))
        return csv_path, midi_path, note_count

    if model_name == "basic_pitch":
        midi_data = _predict_basic_pitch(source)
    elif model_name == "magenta":
        midi_data = _predict_magenta(
            source, Path(model_dir).expanduser().resolve()
        )
    elif model_name == "bytedance":
        midi_data = _predict_bytedance(
            source, Path(model_dir).expanduser().resolve()
        )
    else:
        midi_data = _predict_omnizart(source)

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
            "Spotify Basic Pitch is unavailable in its container image. "
            "Run `make install`."
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
            "Google Magenta is not installed in its container image. "
            "Run `make install`."
        )

    checkpoint_dir = _require_magenta_checkpoint(model_dir)
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

        midi_path = Path(str(temporary_audio) + ".midi")
        if not midi_path.is_file():
            raise RuntimeError(
                "Google Magenta finished without producing a MIDI transcription."
            )
        return pretty_midi.PrettyMIDI(str(midi_path))


def _predict_bytedance(audio_path: Path, model_dir: Path) -> MidiData:
    try:
        import librosa
        import pretty_midi
        from piano_transcription_inference import (
            PianoTranscription,
            sample_rate,
        )
    except ImportError as exc:
        raise RuntimeError(
            "ByteDance Piano Transcription is unavailable in its container."
        ) from exc

    checkpoint = model_dir / "bytedance" / "piano_transcription.pth"
    if not checkpoint.is_file():
        raise RuntimeError(
            "The ByteDance checkpoint is not installed. Run `make install`."
        )
    audio, _ = librosa.load(str(audio_path), sr=sample_rate, mono=True)
    with tempfile.TemporaryDirectory(prefix="kivipiano-bytedance-") as temp_dir:
        midi_path = Path(temp_dir) / "transcription.mid"
        transcriber = PianoTranscription(
            device="cpu", checkpoint_path=str(checkpoint)
        )
        transcriber.transcribe(audio, str(midi_path))
        if not midi_path.is_file():
            raise RuntimeError(
                "ByteDance Piano Transcription finished without producing MIDI."
            )
        return pretty_midi.PrettyMIDI(str(midi_path))


def _predict_omnizart(audio_path: Path) -> MidiData:
    try:
        import pretty_midi
    except ImportError as exc:
        raise RuntimeError(
            "pretty-midi is unavailable in the Omnizart container."
        ) from exc

    with tempfile.TemporaryDirectory(prefix="kivipiano-omnizart-") as temp_dir:
        output_dir = Path(temp_dir)
        environment = os.environ.copy()
        environment["HOME"] = "/models/omnizart"
        completed = subprocess.run(
            [
                "omnizart",
                "music",
                "transcribe",
                str(audio_path),
                "--output",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        if completed.returncode:
            details = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(
                "Omnizart transcription failed"
                + (f":\n{details[-2000:]}" if details else ".")
            )
        midi_files = list(output_dir.rglob("*.mid")) + list(
            output_dir.rglob("*.midi")
        )
        if not midi_files:
            raise RuntimeError(
                "Omnizart finished without producing a MIDI transcription."
            )
        return pretty_midi.PrettyMIDI(str(midi_files[0]))


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

    located = shutil.which("onsets_frames_transcription_transcribe")
    return Path(located) if located else None


def magenta_checkpoint_dir(model_dir: Path) -> Path:
    """Return the directory where the Magenta checkpoint is stored."""
    return Path(model_dir).expanduser().resolve() / "magenta" / "maestro_checkpoint"


def _has_magenta_checkpoint(checkpoint_dir: Path) -> bool:
    return any(checkpoint_dir.glob("*.index"))


def download_magenta_checkpoint(model_dir: Path) -> Path:
    """Download the Magenta checkpoint into ``model_dir`` (install-time only).

    This is run by ``make install`` so the application never downloads models
    while it is running.
    """
    checkpoint_dir = magenta_checkpoint_dir(model_dir)
    if _has_magenta_checkpoint(checkpoint_dir):
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

    if not _has_magenta_checkpoint(checkpoint_dir):
        raise RuntimeError(
            "The Magenta checkpoint was downloaded, but its expected train "
            "checkpoint was not found."
        )
    return checkpoint_dir


def _require_magenta_checkpoint(model_dir: Path) -> Path:
    """Return the pre-downloaded Magenta checkpoint, without downloading it."""
    checkpoint_dir = magenta_checkpoint_dir(model_dir)
    if not _has_magenta_checkpoint(checkpoint_dir):
        raise RuntimeError(
            "The Google Magenta checkpoint is not installed. Run `make install` "
            "to download all models before using the app."
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
