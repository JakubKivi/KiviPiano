import csv
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pretty_midi

from kivipiano.transcription import (
    _ensure_magenta_checkpoint,
    transcribe_piano,
)


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.audio_path = self.root / "piano.wav"
        self.audio_path.touch()

    def test_basic_pitch_writes_midi_and_normalized_note_csv(self):
        notes = [
            SimpleNamespace(start=1.5, end=2.0, pitch=64, velocity=90),
            SimpleNamespace(start=0.25, end=0.75, pitch=60, velocity=80),
        ]

        def write_midi(path):
            Path(path).write_bytes(b"midi")

        midi_data = SimpleNamespace(
            instruments=[SimpleNamespace(notes=notes)],
            write=write_midi,
        )
        output_dir = self.root / "output"
        with patch(
            "kivipiano.transcription._predict_basic_pitch",
            return_value=midi_data,
        ):
            csv_path, midi_path, note_count = transcribe_piano(
                str(self.audio_path),
                str(output_dir),
                str(self.root / "models"),
            )

        self.assertEqual(note_count, 2)
        self.assertTrue(midi_path.is_file())
        with csv_path.open(encoding="utf-8", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(
            rows,
            [
                {
                    "start_time": "0.250000",
                    "end_time": "0.750000",
                    "pitch": "60",
                    "velocity": "80",
                    "model": "basic_pitch",
                },
                {
                    "start_time": "1.500000",
                    "end_time": "2.000000",
                    "pitch": "64",
                    "velocity": "90",
                    "model": "basic_pitch",
                },
            ],
        )

    def test_rejects_unknown_transcription_model(self):
        with self.assertRaisesRegex(ValueError, "Unknown transcription model"):
            transcribe_piano(
                str(self.audio_path),
                str(self.root / "output"),
                str(self.root / "models"),
                "unknown",
            )

    def test_downloads_and_caches_magenta_checkpoint(self):
        model_dir = self.root / "models"

        def create_checkpoint(_url, archive_path):
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("maestro/train/model.index", b"checkpoint")
                archive.writestr("maestro/train/model.data-00000-of-00001", b"data")
            return str(archive_path), None

        with patch(
            "kivipiano.transcription.urlretrieve",
            side_effect=create_checkpoint,
        ) as download:
            checkpoint = _ensure_magenta_checkpoint(model_dir)
            cached_checkpoint = _ensure_magenta_checkpoint(model_dir)

        self.assertEqual(checkpoint, model_dir / "magenta" / "maestro_checkpoint")
        self.assertEqual(cached_checkpoint, checkpoint)
        self.assertTrue((checkpoint / "model.index").is_file())
        download.assert_called_once()

    def test_magenta_cli_output_is_normalized_to_csv_and_midi(self):
        executable = self.root / "magenta.exe"
        executable.touch()
        checkpoint = self.root / "checkpoint"

        def transcribe(args, **_kwargs):
            audio_path = Path(args[2])
            midi_data = pretty_midi.PrettyMIDI()
            instrument = pretty_midi.Instrument(program=0)
            instrument.notes.append(
                pretty_midi.Note(
                    velocity=92, pitch=60, start=0.1, end=0.6
                )
            )
            midi_data.instruments.append(instrument)
            midi_data.write(str(audio_path.with_suffix(".midi")))
            return SimpleNamespace(returncode=0, stderr="", stdout="")

        with (
            patch(
                "kivipiano.transcription._magenta_executable",
                return_value=executable,
            ),
            patch(
                "kivipiano.transcription._ensure_magenta_checkpoint",
                return_value=checkpoint,
            ),
            patch(
                "kivipiano.transcription.subprocess.run",
                side_effect=transcribe,
            ),
        ):
            csv_path, midi_path, note_count = transcribe_piano(
                str(self.audio_path),
                str(self.root / "output"),
                str(self.root / "models"),
                "magenta",
            )

        self.assertEqual(note_count, 1)
        self.assertTrue(midi_path.is_file())
        with csv_path.open(encoding="utf-8", newline="") as csv_file:
            row = next(csv.DictReader(csv_file))
        self.assertEqual(row["pitch"], "60")
        self.assertEqual(row["model"], "magenta")

    def test_magenta_requires_its_optional_runtime(self):
        with patch("kivipiano.transcription._magenta_executable", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Google Magenta is not installed"):
                transcribe_piano(
                    str(self.audio_path),
                    str(self.root / "output"),
                    str(self.root / "models"),
                    "magenta",
                )


if __name__ == "__main__":
    unittest.main()
