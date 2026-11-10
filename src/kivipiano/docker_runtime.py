"""Run one-shot model workers in their isolated Docker images."""

import os
from pathlib import Path
import subprocess


MODEL_IMAGES = {
    "demucs": "kivipiano-demucs:latest",
    "spleeter": "kivipiano-spleeter:latest",
    "basic_pitch": "kivipiano-basic-pitch:latest",
    "magenta": "kivipiano-magenta:latest",
    "bytedance": "kivipiano-bytedance:latest",
    "mt3": "kivipiano-mt3:latest",
    "omnizart": "kivipiano-omnizart:latest",
}


def image_available(model_name: str) -> bool:
    """Return whether the model's Docker image is built locally."""
    image = MODEL_IMAGES.get(model_name)
    if image is None:
        raise ValueError(f"Unknown model container: {model_name}")
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def run_model_container(
    model_name: str,
    operation: str,
    model_dir: str | Path,
    audio_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    stem_name: str | None = None,
) -> None:
    """Run a worker with only its model, input, and output directories mounted."""
    image = MODEL_IMAGES.get(model_name)
    if image is None:
        raise ValueError(f"Unknown model container: {model_name}")
    if operation not in {"prepare", "transcribe", "separate"}:
        raise ValueError(f"Unknown container operation: {operation}")

    model_path = Path(model_dir).expanduser().resolve()
    model_path.mkdir(parents=True, exist_ok=True)
    command = ["docker", "run", "--rm"]
    if operation != "prepare":
        command.extend(["--network", "none"])
    command.extend(
        [
            "--mount",
            f"type=bind,source={model_path},target=/models",
            "-e",
            "KIVIPIANO_CONTAINER_WORKER=1",
            "-e",
            "HF_HOME=/models/huggingface",
            "-e",
            "HF_HUB_OFFLINE=1" if operation != "prepare" else "HF_HUB_OFFLINE=0",
            "-e",
            "MODEL_PATH=/models/spleeter",
            "-e",
            (
                "HOME=/models/omnizart"
                if model_name == "omnizart"
                else "HOME=/models/home"
            ),
        ]
    )

    input_in_container = ""
    if audio_path is not None:
        source = Path(audio_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Audio file does not exist: {source}")
        command.extend(
            [
                "--mount",
                f"type=bind,source={source},target=/input/{source.name},readonly",
            ]
        )
        input_in_container = f"/input/{source.name}"

    output_in_container = ""
    if output_dir is not None:
        destination = Path(output_dir).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        command.extend(
            [
                "--mount",
                f"type=bind,source={destination},target=/output",
            ]
        )
        output_in_container = "/output"

    command.extend(
        [
            image,
            "python",
            "-m",
            "kivipiano.container_worker",
            operation,
            model_name,
            input_in_container,
            output_in_container,
            stem_name or "",
        ]
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if result.returncode:
        details = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"{model_name} Docker {operation} failed"
            + (f":\n{details[-3000:]}" if details else ".")
        )
