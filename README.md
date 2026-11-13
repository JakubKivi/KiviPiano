# KiviPiano
From MP3 file to LED indicators on your piano

## Audio separation

On Windows, install Python 3.11, GNU Make, and Docker Desktop (with Linux
containers enabled), then run `make install` once and start the app with
`make run`. The app and its GUI run in the project-local `.venv` (Python 3.11);
each separator and transcription model runs in its own Docker image (Python
3.10 — a separate, isolated runtime, so the two versions never conflict).
`make install`
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
and Omnizart each run in a separate container. Each writes a MIDI
file and normalized CSV (`start_time`, `end_time`, `pitch`, `velocity`,
`model`) beside the separated stem.

Processing is incremental: when the separated stem or a model's MIDI/CSV
already exists, KiviPiano reuses it instead of re-running its container.
Changing only the fusion weights therefore re-runs just the final fusion
step. To force a step to be recomputed, delete its intermediate output (the
stem WAV under `htdemucs_6s`/`spleeter_5stems`, or the model's `*.csv` and
`*.mid`).

### Beat & chord refinement

Between the AMT models and the note filters, an optional **Beats & Chords**
stage (`src/kivipiano/musical_context.py`) analyses the separated piano stem
with Madmom to recover its beat grid and chord progression, then refines the
fused notes against that musical context:

- **Beat snapping** — a note whose onset sits close to a beat is snapped onto
  it (fixing slight timing shifts when chords are struck), keeping its
  duration.
- **Chord false-positive filter** — a note that is both off the grid and not a
  member of the sounding chord is dropped as a likely false positive. Chord
  tones and on-beat notes (melody) are always kept.

The stage is disabled by default; enable it in the **Beats & Chords** step
(step 4). Its beat/chord analysis is cached as a JSON file beside the stem and
reused, so changing only the refinement settings re-runs just that step.

### Note filtering

After fusion, the consensus notes pass through a configurable cleanup
pipeline (`src/kivipiano/filters.py`) that removes common artifacts. The
**Filters** step (step 5, between AMT models and MIDI) lets you toggle and
tune each filter while previewing the effect live on a piano roll, then apply
the result to the fused MIDI:

- **Duration gate** — drops notes shorter than a minimum length
  (percussion/sibilant noise).
- **Velocity gate** — drops notes quieter than an adaptive velocity
  percentile of the piece (vocal bleed).
- **Pitch band-pass** — keeps only a MIDI pitch range (cuts cymbal bleed and
  bass rumble).
- **Note merging** — stitches same-pitch notes separated by a tiny gap back
  into one long note.
- **Polyphony limit** — keeps only the loudest few notes in each 50 ms window.
- **Overtone suppression** — drops a quiet note 12/19 semitones above a louder
  overlapping note (ghost harmonics).

Filters follow the same registry/protocol pattern as the fusion strategies:
implement `NoteFilter`, register it in `NOTE_FILTERS`, and add it to
`FILTER_ORDER` and `FilterConfig` to make it available.


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
