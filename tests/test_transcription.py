import csv
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pretty_midi

from kivipiano.transcription import (
    AMT_MODELS,
    _require_magenta_checkpoint,
    download_magenta_checkpoint,
    magenta_available,
    magenta_checkpoint_dir,
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
        with (
            patch.dict(os.environ, {"KIVIPIANO_CONTAINER_WORKER": "1"}),
            patch(
                "kivipiano.transcription._predict_basic_pitch",
                return_value=midi_data,
            ),
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
            checkpoint = download_magenta_checkpoint(model_dir)
            cached_checkpoint = download_magenta_checkpoint(model_dir)

        self.assertEqual(checkpoint, magenta_checkpoint_dir(model_dir))
        self.assertEqual(cached_checkpoint, checkpoint)
        self.assertTrue((checkpoint / "model.index").is_file())
        download.assert_called_once()

    def test_requires_magenta_checkpoint_without_downloading(self):
        model_dir = self.root / "models"
        with patch(
            "kivipiano.transcription.urlretrieve",
        ) as download:
            with self.assertRaisesRegex(RuntimeError, "checkpoint is not installed"):
                _require_magenta_checkpoint(model_dir)
        download.assert_not_called()

        checkpoint = model_dir / "magenta" / "maestro_checkpoint"
        checkpoint.mkdir(parents=True)
        (checkpoint / "model.index").touch()
        self.assertEqual(_require_magenta_checkpoint(model_dir), checkpoint)

    def test_magenta_available_requires_executable_and_checkpoint(self):
        model_dir = self.root / "models"

        with patch(
            "kivipiano.transcription.image_available", return_value=False
        ):
            self.assertFalse(magenta_available(model_dir))

        checkpoint = model_dir / "magenta" / "maestro_checkpoint"
        checkpoint.mkdir(parents=True)
        (checkpoint / "model.index").touch()
        with patch(
            "kivipiano.transcription.image_available", return_value=True
        ):
            self.assertTrue(magenta_available(model_dir))

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
            midi_data.write(str(audio_path) + ".midi")
            return SimpleNamespace(returncode=0, stderr="", stdout="")

        with (
            patch.dict(os.environ, {"KIVIPIANO_CONTAINER_WORKER": "1"}),
            patch(
                "kivipiano.transcription._magenta_executable",
                return_value=executable,
            ),
            patch(
                "kivipiano.transcription._require_magenta_checkpoint",
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
        with (
            patch.dict(os.environ, {"KIVIPIANO_CONTAINER_WORKER": "1"}),
            patch("kivipiano.transcription._magenta_executable", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "Google Magenta is not installed"):
                transcribe_piano(
                    str(self.audio_path),
                    str(self.root / "output"),
                    str(self.root / "models"),
                    "magenta",
                )

    def test_all_transcription_models_run_in_their_own_container(self):
        models_dir = self.root / "models"
        for model_name in AMT_MODELS:
            with self.subTest(model=model_name):
                output_dir = self.root / model_name

                def transcribe_in_container(
                    container_name,
                    operation,
                    _model_dir,
                    _audio_path,
                    destination,
                    _stem_name=None,
                ):
                    self.assertEqual(container_name, model_name)
                    self.assertEqual(operation, "transcribe")
                    destination = Path(destination)
                    stem = f"{self.audio_path.stem}_{model_name}"
                    (destination / f"{stem}.mid").write_bytes(b"midi")
                    (destination / f"{stem}.csv").write_text(
                        "start_time,end_time,pitch,velocity,model\n"
                        f"0.1,0.2,60,90,{model_name}\n",
                        encoding="utf-8",
                    )

                with patch(
                    "kivipiano.transcription.run_model_container",
                    side_effect=transcribe_in_container,
                ):
                    csv_path, midi_path, note_count = transcribe_piano(
                        str(self.audio_path),
                        str(output_dir),
                        str(models_dir),
                        model_name,
                    )

                self.assertEqual(note_count, 1)
                self.assertTrue(csv_path.is_file())
                self.assertTrue(midi_path.is_file())


if __name__ == "__main__":
    unittest.main()
