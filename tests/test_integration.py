"""End-to-end smoke tests against the real Docker model containers.

These tests download a YouTube video once, save it to the library, then reuse
that saved file for every separation and transcription. They are slow and
require Docker Desktop plus the pre-downloaded models, so they are excluded
from the default ``make test`` run and only execute when the environment
variable ``KIVIPIANO_E2E=1`` is set.

Example::

    KIVIPIANO_E2E=1 .venv/Scripts/python.exe -m unittest tests.test_integration -v
"""

import os
import unittest
from pathlib import Path

from kivipiano.config import AppPaths
from kivipiano.media import download_youtube_audio, list_saved_audio
from kivipiano.separation import separate_stem
from kivipiano.services.processing import (
    AudioProcessingService,
    ModelWeight,
    ProcessingRequest,
)
from kivipiano.transcription import AMT_MODELS, transcribe_piano

YOUTUBE_URL = "https://www.youtube.com/watch?v=Bu_LBqIECoQ"
VIDEO_ID = "Bu_LBqIECoQ"
STEM_NAME = "piano"
SEPARATORS = ("demucs", "spleeter")
AMT_NAMES = tuple(AMT_MODELS)


@unittest.skipUnless(
    os.environ.get("KIVIPIANO_E2E") == "1",
    "End-to-end tests need Docker and are run explicitly.",
)
class EndToEndSmokeTests(unittest.TestCase):
    """Drive each separator and AMT model through the real containers."""

    paths = AppPaths.default()

    # -- cached fixtures (idempotent across processes) ----------------------

    @classmethod
    def library_audio(cls) -> Path:
        """Return the downloaded MP3, reusing a previous download."""
        for path in list_saved_audio(cls.paths.library_dir):
            if VIDEO_ID in path.name:
                return path
        print(f"\n>>> Downloading {YOUTUBE_URL} to the library ...", flush=True)
        return download_youtube_audio(YOUTUBE_URL, cls.paths.library_dir)

    @classmethod
    def stem(cls, separator: str) -> Path:
        """Return the piano stem, separating only if not already present."""
        audio = cls.library_audio()
        output_path = cls.paths.output_dir
        if separator == "demucs":
            expected = (
                output_path / "htdemucs_6s" / f"demucs_{audio.stem}_{STEM_NAME}.wav"
            )
        else:
            expected = (
                output_path / "spleeter_5stems" / f"spleeter_{audio.stem}_{STEM_NAME}.wav"
            )
        if expected.is_file():
            return expected
        print(f"\n>>> Separating the {STEM_NAME} stem with {separator} ...", flush=True)
        return separate_stem(
            str(audio),
            str(output_path),
            str(cls.paths.model_dir),
            separator_name=separator,
            stem_name=STEM_NAME,
        )

    def _transcribe(self, model: str) -> None:
        stem = self.stem("demucs")
        print(f"\n>>> Transcribing with {AMT_MODELS[model]} ...", flush=True)
        csv_path, midi_path, note_count = transcribe_piano(
            str(stem),
            str(self.paths.output_dir),
            str(self.paths.model_dir),
            model_name=model,
        )
        print(
            f"    -> {note_count} notes; MIDI={midi_path.name}; CSV={csv_path.name}",
            flush=True,
        )
        self.assertTrue(csv_path.is_file(), f"{model} CSV missing")
        self.assertTrue(midi_path.is_file(), f"{model} MIDI missing")
        self.assertGreater(note_count, 0, f"{model} produced no notes")

    # -- tests --------------------------------------------------------------

    def test_01_download_youtube_to_library(self):
        audio = self.library_audio()
        self.assertTrue(audio.is_file())
        self.assertEqual(audio.suffix.lower(), ".mp3")

    def test_02_demucs_separation(self):
        self.assertTrue(self.stem("demucs").is_file())

    def test_03_spleeter_separation(self):
        self.assertTrue(self.stem("spleeter").is_file())

    def test_04_transcribe_basic_pitch(self):
        self._transcribe("basic_pitch")

    def test_05_transcribe_magenta(self):
        self._transcribe("magenta")

    def test_06_transcribe_bytedance(self):
        self._transcribe("bytedance")

    def test_07_transcribe_omnizart(self):
        self._transcribe("omnizart")

    def test_08_full_pipeline_from_saved_file(self):
        audio = self.library_audio()
        service = AudioProcessingService(self.paths)
        result = service.process(
            ProcessingRequest(
                source_mode="file",
                source=str(audio),
                save_for_later=False,
                separator="demucs",
                stem=STEM_NAME,
                amt_models=(ModelWeight("basic_pitch", 1.0),),
            ),
            on_progress=lambda message: print(f"    [progress] {message}", flush=True),
        )
        self.assertTrue(result.output_path.is_file())
        self.assertTrue(result.midi_path.is_file())
        self.assertGreater(result.midi_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
