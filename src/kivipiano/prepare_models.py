"""Pre-download every model KiviPiano needs before the app is first run.

Run with ``python -m kivipiano.prepare_models`` (normally invoked automatically
by ``make install``). Every model checkpoint is downloaded into
``~/.kivipiano/models`` so containers never need network access during inference.
"""

import sys
from pathlib import Path

from kivipiano.config import AppPaths
from kivipiano.docker_runtime import MODEL_IMAGES, run_model_container


def prepare_all(model_dir: Path) -> None:
    """Download every model KiviPiano needs into ``model_dir``."""
    model_path = Path(model_dir).expanduser().resolve()
    model_path.mkdir(parents=True, exist_ok=True)

    for model_name in MODEL_IMAGES:
        print(f"Preparing {model_name} container and model...")
        run_model_container(model_name, "prepare", model_path)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    model_dir = AppPaths.default().model_dir
    if len(args) > 1:
        print(f"Usage: python -m kivipiano.prepare_models [MODEL_DIR]", file=sys.stderr)
        return 2
    if len(args) == 1:
        model_dir = Path(args[0])

    print(f"Downloading KiviPiano models into {model_dir} ...")
    prepare_all(model_dir)
    print("All KiviPiano models are ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
