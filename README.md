# KiviPiano
From MP3 file to LED indicators on your piano

## Audio separation

On Windows, install Python 3.11, GNU Make, and Docker Desktop (with Linux
containers enabled), then run `make install` once and start the app with
`make run`. The app and its GUI run in the project-local `.venv`; each
separator and transcription model runs in its own Docker image. `make install`
builds all seven model images and downloads every model into
`~/.kivipiano/models`. During processing, the workers run without network
access, so inference never downloads software or checkpoints. Any model whose
image or checkpoint is missing is shown greyed out in the app. Choose
an MP3/WAV file or paste a single-video YouTube URL. YouTube audio is
downloaded with yt-dlp and converted to MP3 by FFmpeg, then sent through the
selected audio-separation and piano-transcription pipeline.
`imageio-ffmpeg` provides FFmpeg for conversion. Demucs also requires
FFmpeg and `ffprobe`, which are included in its container image.

You can keep downloaded audio or a copy of a selected file in the in-app
library at `~/.kivipiano/library`, then choose it from the **Saved Files** tab
on a later run. Unchecked YouTube downloads are temporary and removed after
processing. Extracted stem WAVs for ordinary files are saved under
`KiviPiano_output` beside the input. Temporary YouTube downloads save their
separated stems under `~/.kivipiano/output`.

Choose either Demucs or Spleeter; selecting one automatically deselects the
other. Each model offers its available stems in the **Stem** selector:
Demucs `htdemucs_6s` provides drums, bass, other, vocals, guitar, and piano;
Spleeter `5stems` provides vocals, piano, drums, bass, and other. All model
files are downloaded during `make install` and cached under
`~/.kivipiano/models`. Output filenames start with `demucs_` or `spleeter_`
and include the selected stem.

## Piano transcription

After separation, choose exactly one AMT model and click **Process**. Spotify
Basic Pitch, Google Magenta Onsets & Frames, ByteDance Piano Transcription,
Google MT3, and Omnizart each run in a separate container. Each writes a MIDI
file and normalized CSV (`start_time`, `end_time`, `pitch`, `velocity`,
`model`) beside the separated stem.

Docker Desktop must be running when you call `make install` and `make run`.
`make install` builds the isolated model images and pre-downloads their model
checkpoints; `make run` keeps the model workers network-isolated. Always use
`make run` to start the app. Errors are displayed in the application.

The Demucs model is public and does not require a Hugging Face account or
token. Model downloads may be subject to anonymous rate limits.

## Development

The application uses a `src/kivipiano` package: the UI, processing service,
media library, separator backends, and path configuration are kept in separate
modules. Run the standard-library unit tests with `make test`.
