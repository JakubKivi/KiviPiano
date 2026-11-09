# KiviPiano
From MP3 file to LED indicators on your piano

## Audio separation

On Windows, install Python 3.11 and GNU Make, then run `make install` once and
start the app with `make run`. Both commands use the same project-local
`.venv`, so Demucs and Spleeter are available to the app without a second
Python interpreter. Choose an MP3/WAV file or paste a single-video YouTube
URL. YouTube audio is downloaded with yt-dlp and converted to MP3 by FFmpeg,
then sent through the selected audio-separation and piano-transcription
pipeline.
`imageio-ffmpeg` provides FFmpeg for conversion. Demucs also requires
`ffprobe`; on Windows install it with
`winget install --id Gyan.FFmpeg.Shared`. The application detects this
installation automatically.

You can keep downloaded audio or a copy of a selected file in the in-app
library at `~/.kivipiano/library`, then choose it from the **Saved Files** tab
on a later run. Unchecked YouTube downloads are temporary and removed after
processing. Extracted stem WAVs for ordinary files are saved under
`KiviPiano_output` beside the input. Temporary YouTube downloads save their
separated stems under `~/.kivipiano/output`.

Choose either Demucs or Spleeter; selecting one automatically deselects the
other. Each model offers its available stems in the **Stem** selector:
Demucs `htdemucs_6s` provides drums, bass, other, vocals, guitar, and piano;
Spleeter `5stems` provides vocals, piano, drums, bass, and other. Model files
are downloaded on first use and cached under `~/.kivipiano/models`. Output
filenames start with `demucs_` or `spleeter_` and include the selected stem.

## Piano transcription

After separation, choose exactly one AMT model and click **Process**. Spotify
Basic Pitch is installed with `make install` and is selected by default. It
transcribes the separated audio and writes a MIDI file and a normalized CSV
(`start_time`, `end_time`, `pitch`, `velocity`, `model`) beside the separated
stem.

Google Magenta Onsets & Frames is available as an optional backend. Its legacy
TensorFlow dependencies conflict with the application's Python 3.11/Spleeter
environment, so install it separately with Python 3.10 available and
`make install-magenta`. The Magenta checkpoint is downloaded and cached under
`~/.kivipiano/models` the first time that model is used. It also writes MIDI
and normalized CSV output alongside the separated audio.

Spleeter 2.4.2 requires Python 3.8 through 3.11. `make install` creates a
Python 3.11 environment and installs the app, both separator dependencies, and
Spotify Basic Pitch in that same environment. Its pinned TensorFlow I/O
dependency does not have a compatible Windows wheel, so Spleeter itself is
installed without reinstalling dependencies after TensorFlow's compatible
version is installed. Always use `make run` to start the app with this
environment. Errors are displayed in the application.

The Demucs model is public and does not require a Hugging Face account or
token. Hugging Face may print an informational warning when downloading without
a token; anonymous downloads still work, but can be subject to lower rate
limits.

## Development

The application uses a `src/kivipiano` package: the UI, processing service,
media library, separator backends, and path configuration are kept in separate
modules. Run the standard-library unit tests with `make test`.
