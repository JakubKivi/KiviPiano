"""Container entry point for isolated audio-model operations."""

import argparse
import os
from pathlib import Path
import subprocess
from urllib.request import urlretrieve


BYTEDANCE_CHECKPOINT_URL = (
    "https://zenodo.org/record/4034264/files/"
    "CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"
)


def _prepare(model_name: str, model_dir: Path) -> None:
    from kivipiano.separation import (
        download_demucs_model,
        download_spleeter_model,
    )
    from kivipiano.transcription import (
        download_magenta_checkpoint,
    )

    if model_name == "demucs":
        download_demucs_model(model_dir)
    elif model_name == "spleeter":
        download_spleeter_model(model_dir)
    elif model_name == "basic_pitch":
        from basic_pitch.inference import predict  # noqa: F401
    elif model_name == "magenta":
        download_magenta_checkpoint(model_dir)
    elif model_name == "bytedance":
        checkpoint = model_dir / "bytedance" / "piano_transcription.pth"
        if not checkpoint.is_file() or checkpoint.stat().st_size < 160_000_000:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            urlretrieve(BYTEDANCE_CHECKPOINT_URL, checkpoint)
        if checkpoint.stat().st_size < 160_000_000:
            raise RuntimeError("The ByteDance checkpoint download is incomplete.")
    elif model_name == "mt3":
        checkpoint_dir = model_dir / "mt3" / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        if not any(checkpoint_dir.rglob("checkpoint*")):
            result = subprocess.run(
                [
                    "gsutil",
                    "-m",
                    "cp",
                    "-r",
                    "gs://mt3/checkpoints/mt3",
                    str(checkpoint_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                details = (result.stderr or result.stdout).strip()
                raise RuntimeError(
                    "Could not download the Google MT3 checkpoint"
                    + (f":\n{details[-2000:]}" if details else ".")
                )
        if not any(checkpoint_dir.rglob("checkpoint*")):
            raise RuntimeError("The Google MT3 checkpoint was not downloaded.")
    elif model_name == "omnizart":
        marker = model_dir / "omnizart" / ".checkpoints-ready"
        if not marker.is_file():
            env = os.environ.copy()
            env["HOME"] = str(model_dir / "omnizart")
            result = subprocess.run(
                ["omnizart", "download-checkpoints"],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            if result.returncode:
                details = (result.stderr or result.stdout).strip()
                raise RuntimeError(
                    "Could not download Omnizart checkpoints"
                    + (f":\n{details[-2000:]}" if details else ".")
                )
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
    else:
        raise ValueError(f"Unknown model container: {model_name}")


def _run_separation(
    model_name: str, audio_path: Path, output_dir: Path, stem_name: str
) -> None:
    from kivipiano.separation import separate_stem

    separate_stem(
        str(audio_path),
        str(output_dir),
        "/models",
        separator_name=model_name,
        stem_name=stem_name,
    )


def _run_transcription(
    model_name: str, audio_path: Path, output_dir: Path
) -> None:
    from kivipiano.transcription import transcribe_piano

    transcribe_piano(
        str(audio_path),
        str(output_dir),
        "/models",
        model_name=model_name,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("prepare", "transcribe", "separate"))
    parser.add_argument("model_name")
    parser.add_argument("audio_path", nargs="?", default="")
    parser.add_argument("output_dir", nargs="?", default="")
    parser.add_argument("stem_name", nargs="?", default="")
    args = parser.parse_args()

    os.environ["KIVIPIANO_CONTAINER_WORKER"] = "1"
    model_dir = Path("/models")
    if args.operation == "prepare":
        _prepare(args.model_name, model_dir)
        return

    audio_path = Path(args.audio_path)
    output_dir = Path(args.output_dir)
    if not audio_path.is_file():
        raise FileNotFoundError(f"Container input audio does not exist: {audio_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.operation == "separate":
        _run_separation(args.model_name, audio_path, output_dir, args.stem_name)
    else:
        _run_transcription(args.model_name, audio_path, output_dir)


if __name__ == "__main__":
    main()
