import tempfile
import unittest
from pathlib import Path

from kivipiano.separation import _spleeter_model_cached, separate_stem


class SeparationValidationTests(unittest.TestCase):
    def test_requires_an_existing_audio_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.mp3"
            with self.assertRaises(FileNotFoundError):
                separate_stem(str(missing), temp_dir, temp_dir)

    def test_rejects_unsupported_input_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "song.flac"
            source.touch()
            with self.assertRaisesRegex(ValueError, "Only MP3 and WAV"):
                separate_stem(str(source), temp_dir, temp_dir)

    def test_rejects_unknown_separator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "song.wav"
            source.touch()
            with self.assertRaisesRegex(ValueError, "Unknown audio separator"):
                separate_stem(
                    str(source), temp_dir, temp_dir, separator_name="unknown"
                )

    def test_rejects_stems_not_supported_by_the_selected_separator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "song.mp3"
            source.touch()
            with self.assertRaisesRegex(ValueError, "does not provide"):
                separate_stem(
                    str(source),
                    temp_dir,
                    temp_dir,
                    separator_name="spleeter",
                    stem_name="guitar",
                )

    def test_spleeter_model_cached_detects_probe_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertFalse(_spleeter_model_cached(root))

            probe_dir = root / "spleeter" / "5stems"
            probe_dir.mkdir(parents=True)
            (probe_dir / ".probe").touch()
            self.assertTrue(_spleeter_model_cached(root))


if __name__ == "__main__":
    unittest.main()
