"""Container entry point for isolated audio-model operations."""

import argparse
import os
from pathlib import Path
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
    from kivipiano.transcription import download_magenta_checkpoint

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
    elif model_name == "omnizart":
        # The music_piano checkpoint is baked into the image at build time
        # (see docker/Dockerfile), so install only records a ready marker.
        marker = model_dir / "omnizart" / ".checkpoints-ready"
        if not marker.is_file():
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
    elif model_name == "madmom":
        # Madmom's beat/chord models ship inside the pip package, so there is
        # nothing to download; install just verifies the image is usable.
        from madmom.features.beats import RNNBeatProcessor  # noqa: F401
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


def _run_analysis(model_name: str, audio_path: Path, output_dir: Path) -> None:
    from kivipiano.musical_context import analyze_musical_context

    analyze_musical_context(str(audio_path), str(output_dir), "/models")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation", choices=("prepare", "transcribe", "separate", "analyze")
    )
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
    elif args.operation == "analyze":
        _run_analysis(args.model_name, audio_path, output_dir)
    else:
        _run_transcription(args.model_name, audio_path, output_dir)


if __name__ == "__main__":
    main()
