"""Audio stem separation backends."""

import os
from pathlib import Path
import shutil

from kivipiano.docker_runtime import image_available, run_model_container


DEMUCS_PIANO_MODEL = "htdemucs_6s"
SPLEETER_PIANO_MODEL = "spleeter:5stems"
SPLEETER_MODEL_NAME = "5stems"
SEPARATOR_STEMS = {
    "demucs": ("drums", "bass", "other", "vocals", "guitar", "piano"),
    "spleeter": ("vocals", "piano", "drums", "bass", "other"),
}


def download_demucs_model(model_dir: str | Path) -> None:
    """Pre-download the Demucs model into ``model_dir`` (install-time only).

    This is run by ``make install`` so the application never downloads models
    while it is running.
    """
    model_path = Path(model_dir).expanduser().resolve()
    model_path.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(model_path)
    if _demucs_model_cached(model_path):
        return
    try:
        from demucs.api import Separator
    except ImportError as exc:
        raise RuntimeError(
            "Demucs is unavailable in its container image. Run `make install`."
        ) from exc

    Separator(model=DEMUCS_PIANO_MODEL, device="cpu")


def download_spleeter_model(model_dir: str | Path) -> None:
    """Pre-download the Spleeter model into ``model_dir`` (install-time only).

    This is run by ``make install`` so the application never downloads models
    while it is running.
    """
    model_path = Path(model_dir).expanduser().resolve()
    model_path.mkdir(parents=True, exist_ok=True)
    os.environ["MODEL_PATH"] = str(model_path / "spleeter")
    if _spleeter_model_cached(model_path):
        return
    try:
        from spleeter.model.provider import ModelProvider
    except ImportError as exc:
        raise RuntimeError(
            "Spleeter is unavailable in its container image. Run `make install`."
        ) from exc

    ModelProvider.default().get(SPLEETER_MODEL_NAME)


def _demucs_hf_repo_name(name: str) -> str:
    """Mirror ``demucs.hf.hf_repo_name`` for the models this app uses."""
    if name == "htdemucs":
        return "HTDemucs"
    if name.startswith("htdemucs_"):
        return "HTDemucs-" + name[len("htdemucs_"):]
    return "Demucs-" + name


def _demucs_model_cached(model_dir: Path) -> bool:
    """Return whether the Demucs model is already present in ``model_dir``."""
    cache_name = f"models--adefossez--{_demucs_hf_repo_name(DEMUCS_PIANO_MODEL)}"
    snapshots = model_dir / "hub" / cache_name / "snapshots"
    return snapshots.is_dir() and any(snapshots.iterdir())


def _spleeter_model_cached(model_dir: Path) -> bool:
    """Return whether the Spleeter model is already present in ``model_dir``."""
    probe = model_dir / "spleeter" / SPLEETER_MODEL_NAME / ".probe"
    return probe.is_file()


def demucs_available(model_dir: str | Path) -> bool:
    """Return whether Demucs is ready to use (model pre-downloaded)."""
    return image_available("demucs") and _demucs_model_cached(
        Path(model_dir).expanduser().resolve()
    )


def spleeter_available(model_dir: str | Path) -> bool:
    """Return whether Spleeter is ready to use (model pre-downloaded and supported)."""
    return image_available("spleeter") and _spleeter_model_cached(
        Path(model_dir).expanduser().resolve()
    )


def _configure_ffmpeg(require_ffprobe: bool = True) -> None:
    if shutil.which("ffmpeg") and (
        not require_ffprobe or shutil.which("ffprobe")
    ):
        return

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            packages_dir = (
                Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
            )
            for package_pattern in ("Gyan.FFmpeg.Shared_*", "yt-dlp.FFmpeg_*"):
                for package_dir in packages_dir.glob(package_pattern):
                    for binary_dir in package_dir.glob("*/bin"):
                        has_ffmpeg = (binary_dir / "ffmpeg.exe").is_file()
                        has_ffprobe = (binary_dir / "ffprobe.exe").is_file()
                        if has_ffmpeg and (not require_ffprobe or has_ffprobe):
                            os.environ["PATH"] = (
                                str(binary_dir) + os.pathsep + os.environ.get("PATH", "")
                            )
                            return

    required_tools = "FFmpeg and ffprobe" if require_ffprobe else "FFmpeg"
    raise RuntimeError(
        f"Audio separation requires {required_tools}. Install FFmpeg, then restart "
        "the application. On Windows: winget install --id Gyan.FFmpeg.Shared"
    )


def separate_stem(
    audio_path: str,
    output_dir: str,
    model_dir: str,
    separator_name: str = "demucs",
    stem_name: str = "piano",
) -> Path:
    source = Path(audio_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {source}")
    if source.suffix.lower() not in {".mp3", ".wav"}:
        raise ValueError("Only MP3 and WAV input files are supported.")
    if separator_name not in {"demucs", "spleeter"}:
        raise ValueError(f"Unknown audio separator: {separator_name}")
    if stem_name not in SEPARATOR_STEMS[separator_name]:
        raise ValueError(
            f"The {separator_name} model does not provide a {stem_name} stem."
        )

    output_path = Path(output_dir).expanduser().resolve()
    model_path = Path(model_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    model_path.mkdir(parents=True, exist_ok=True)

    if os.environ.get("KIVIPIANO_CONTAINER_WORKER") != "1":
        run_model_container(
            separator_name,
            "separate",
            model_path,
            source,
            output_path,
            stem_name,
        )
        stem_dir = (
            output_path / DEMUCS_PIANO_MODEL
            if separator_name == "demucs"
            else output_path / "spleeter_5stems"
        )
        stem_path = stem_dir / f"{separator_name}_{source.stem}_{stem_name}.wav"
        if not stem_path.is_file():
            raise RuntimeError(
                f"The {separator_name} container finished without producing "
                f"the {stem_name} stem."
            )
        return stem_path

    _configure_ffmpeg(require_ffprobe=separator_name == "demucs")

    if separator_name == "demucs":
        os.environ["HF_HOME"] = str(model_path)
        os.environ["HF_HUB_OFFLINE"] = "1"

        if not _demucs_model_cached(model_path):
            raise RuntimeError(
                "The Demucs model is not installed. Run `make install` to download "
                "all models before using the app."
            )

        try:
            from demucs.api import Separator, save_audio
        except ImportError as exc:
            raise RuntimeError(
                "Demucs is unavailable in its container image. Run `make install`."
            ) from exc

        separator = Separator(model=DEMUCS_PIANO_MODEL, device="cpu")
        if stem_name not in separator.model.sources:
            raise RuntimeError(
                f"The Demucs model {DEMUCS_PIANO_MODEL} does not provide a "
                f"{stem_name} stem."
            )

        _, stems = separator.separate_audio_file(source)
        stem = stems.get(stem_name)
        if stem is None:
            raise RuntimeError(f"Demucs did not return a {stem_name} stem.")

        stem_dir = output_path / DEMUCS_PIANO_MODEL
        stem_dir.mkdir(parents=True, exist_ok=True)
        stem_path = stem_dir / f"demucs_{source.stem}_{stem_name}.wav"
        save_audio(
            stem,
            str(stem_path),
            samplerate=separator.samplerate,
            clip="rescale",
            bits_per_sample=16,
        )
        return stem_path

    if separator_name == "spleeter":
        os.environ["MODEL_PATH"] = str(model_path / "spleeter")

        if not _spleeter_model_cached(model_path):
            raise RuntimeError(
                "The Spleeter model is not installed. Run `make install` to download "
                "all models before using the app."
            )

        try:
            from spleeter.audio import Codec
            from spleeter.audio.adapter import AudioAdapter
            from spleeter.separator import Separator
        except ImportError as exc:
            raise RuntimeError(
                "Spleeter is unavailable. Run KiviPiano with Python 3.11, install "
                "requirements-spleeter.txt, then install Spleeter 2.4.2 with "
                "`python -m pip install --no-deps spleeter==2.4.2`."
            ) from exc

        separator = Separator(SPLEETER_PIANO_MODEL, multiprocess=False)
        audio_adapter = AudioAdapter.default()
        waveform, sample_rate = audio_adapter.load(str(source), sample_rate=44100)
        stems = separator.separate(waveform, str(source))
        stem = stems.get(stem_name)
        if stem is None:
            raise RuntimeError(f"Spleeter did not return a {stem_name} stem.")

        stem_dir = output_path / "spleeter_5stems"
        stem_dir.mkdir(parents=True, exist_ok=True)
        stem_path = stem_dir / f"spleeter_{source.stem}_{stem_name}.wav"
        audio_adapter.save(stem_path, stem, sample_rate, codec=Codec.WAV)
        return stem_path

    raise ValueError(f"Unknown audio separator: {separator_name}")
