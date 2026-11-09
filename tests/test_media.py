import tempfile
import unittest
from pathlib import Path

from kivipiano.media import (
    list_saved_audio,
    save_audio_for_later,
    validate_youtube_url,
)


class ValidateYouTubeUrlTests(unittest.TestCase):
    def test_accepts_youtube_video_urls_and_trims_whitespace(self):
        for url in (
            "https://www.youtube.com/watch?v=abc",
            "http://youtu.be/abc",
            "https://music.youtube.com/watch?v=abc",
        ):
            with self.subTest(url=url):
                self.assertEqual(validate_youtube_url(f"  {url}  "), url)

    def test_rejects_non_youtube_and_malformed_urls(self):
        for url in (
            "",
            "https://youtube.com.evil.example/watch?v=abc",
            "https://youtube.com@evil.example/watch?v=abc",
            "ftp://youtube.com/watch?v=abc",
            "https://youtube.com:444/watch?v=abc",
            "https://youtube.com/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_youtube_url(url)


class AudioLibraryTests(unittest.TestCase):
    def test_lists_supported_files_in_case_insensitive_name_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            library = Path(temp_dir)
            for name in ("z.wav", "A.MP3", "b.txt", "B.mp3"):
                (library / name).touch()
            (library / "folder.mp3").mkdir()

            self.assertEqual(
                [path.name for path in list_saved_audio(library)],
                ["A.MP3", "B.mp3", "z.wav"],
            )

    def test_missing_library_is_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(list_saved_audio(Path(temp_dir) / "missing"), [])

    def test_saves_audio_without_overwriting_existing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "song.mp3"
            source.write_bytes(b"audio")
            library = root / "library"
            (library / source.name).parent.mkdir(parents=True)
            (library / source.name).write_bytes(b"existing")

            saved_path = save_audio_for_later(source, library)

            self.assertEqual(saved_path.name, "song (1).mp3")
            self.assertEqual(saved_path.read_bytes(), b"audio")
            self.assertEqual((library / source.name).read_bytes(), b"existing")

    def test_same_file_is_not_copied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "song.wav"
            source.touch()
            self.assertEqual(save_audio_for_later(source, source.parent), source)

    def test_rejects_unsupported_audio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "song.flac"
            source.touch()
            with self.assertRaises(ValueError):
                save_audio_for_later(source, Path(temp_dir) / "library")


if __name__ == "__main__":
    unittest.main()
