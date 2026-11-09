"""YouTube download and saved-audio library operations."""

import shutil
from pathlib import Path
from urllib.parse import urlsplit


SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".wav"}


def validate_youtube_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise ValueError("Paste a YouTube video URL.")

    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The URL is not valid.") from exc

    is_youtube_host = (
        hostname == "youtu.be"
        or hostname == "youtube.com"
        or (
            hostname.endswith(".youtube.com")
            and hostname != ".youtube.com"
        )
    )
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not is_youtube_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        raise ValueError("Enter a valid http(s) URL from youtube.com or youtu.be.")
    if not parsed.path or parsed.path == "/":
        raise ValueError("The URL does not identify a YouTube video.")
    return value


def download_youtube_audio(url: str, output_dir: Path) -> Path:
    checked_url = validate_youtube_url(url)
    ffmpeg_location = shutil.which("ffmpeg")
    if ffmpeg_location is None:
        try:
            import imageio_ffmpeg

            ffmpeg_location = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, OSError, RuntimeError) as exc:
            raise RuntimeError(
                "FFmpeg was not found. Install the project requirements or install "
                "FFmpeg and make sure it is available on PATH."
            ) from exc
    if not Path(ffmpeg_location).is_file():
        raise RuntimeError(
            "The configured FFmpeg executable could not be found. Install FFmpeg "
            "or reinstall the project requirements."
        )

    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is not installed. Install the project requirements and try again."
        ) from exc

    destination = output_dir.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    output_template = str(destination / "%(title).180B [%(id)s].%(ext)s")
    options = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "ffmpeg_location": ffmpeg_location,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(checked_url, download=False)
            if not info or info.get("_type") in {"playlist", "multi_video"}:
                raise RuntimeError("The URL must point to a single YouTube video.")
            if not info.get("id") or not info.get("title"):
                raise RuntimeError("YouTube did not return valid video information.")

            expected_path = Path(downloader.prepare_filename(info)).with_suffix(".mp3")
            if expected_path.is_file():
                return expected_path

            downloaded_info = downloader.extract_info(checked_url, download=True)
            if not downloaded_info:
                raise RuntimeError("yt-dlp did not return downloaded video information.")
            downloaded_path = Path(
                downloader.prepare_filename(downloaded_info)
            ).with_suffix(".mp3")
            if downloaded_path.is_file():
                return downloaded_path
            if expected_path.is_file():
                return expected_path
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(
            f"yt-dlp could not download or convert this video: {exc}"
        ) from exc

    raise RuntimeError(
        "yt-dlp finished, but the converted MP3 could not be found. "
        "Check that FFmpeg is installed correctly and try again."
    )


def list_saved_audio(library_dir: Path) -> list[Path]:
    directory = library_dir.expanduser()
    if not directory.exists():
        return []
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_SUFFIXES
        ),
        key=lambda path: path.name.casefold(),
    )


def save_audio_for_later(source_path: Path, library_dir: Path) -> Path:
    source = source_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {source}")
    if source.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
        raise ValueError("Only MP3 and WAV audio files can be saved in the library.")

    destination_dir = library_dir.expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / source.name
    if target.resolve() == source:
        return source

    counter = 1
    while target.exists():
        target = destination_dir / f"{source.stem} ({counter}){source.suffix}"
        counter += 1

    shutil.copy2(source, target)
    return target
