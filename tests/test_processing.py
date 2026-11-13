import csv
import tempfile
import unittest
from pathlib import Path

from kivipiano.config import AppPaths
from kivipiano.fusion import FusionConfig
from kivipiano.musical_context import (
    BeatChordAnalysis,
    ChordSegment,
    ContextConfig,
    chord_pitch_classes,
)
from kivipiano.separation import expected_stem_path
from kivipiano.services.processing import (
    AudioProcessingService,
    ModelWeight,
    ProcessingRequest,
)
from kivipiano.transcription import transcription_paths


class AudioProcessingServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.paths = AppPaths(self.root / ".kivipiano")
        self.calls = []
        self.transcriptions = []

    def request(self, **overrides):
        values = {
            "source_mode": "file",
            "source": str(self.root / "source.mp3"),
            "save_for_later": False,
            "separator": "demucs",
            "stem": "piano",
            "amt_models": (ModelWeight("basic_pitch", 1.0),),
        }
        values.update(overrides)
        return ProcessingRequest(**values)

    def make_service(self, downloader=None):
        def separate(source, output_dir, model_dir, separator, stem):
            source_path = Path(source)
            output_path = Path(output_dir)
            self.assertTrue(source_path.is_file())
            output_path.mkdir(parents=True, exist_ok=True)
            result_path = output_path / f"{separator}_{source_path.stem}_{stem}.wav"
            result_path.touch()
            self.calls.append(
                (source_path, output_path, Path(model_dir), separator, stem)
            )
            return result_path

        def transcribe(audio, output_dir, model_dir, model):
            audio_path = Path(audio)
            self.assertTrue(audio_path.is_file())
            output_path = Path(output_dir)
            csv_path = output_path / f"{model}.csv"
            midi_path = output_path / f"{model}.mid"
            csv_path.write_text(
                "start_time,end_time,pitch,velocity,model\n"
                f"0.1,0.2,60,90,{model}\n",
                encoding="utf-8",
            )
            midi_path.touch()
            self.transcriptions.append((audio_path, Path(model_dir), model))
            return csv_path, midi_path, 1

        return AudioProcessingService(
            self.paths,
            downloader=downloader,
            separator=separate,
            transcriber=transcribe,
        )

    def test_processes_a_file_next_to_its_source(self):
        source = self.root / "song.mp3"
        source.touch()

        result = self.make_service().process(self.request(source=str(source)))

        self.assertEqual(result.output_path.parent, self.root / "KiviPiano_output")
        self.assertEqual(result.output_path.name, "demucs_song_piano_fused.csv")
        self.assertEqual(result.midi_path.name, "demucs_song_piano_fused.mid")
        self.assertTrue(result.midi_path.is_file())
        self.assertIsNone(result.selected_audio)
        self.assertEqual(self.calls[0][2], self.paths.model_dir)
        self.assertEqual(self.transcriptions[0][1], self.paths.model_dir)
        self.assertEqual(self.transcriptions[0][2], "basic_pitch")

    def test_selects_the_requested_transcription_model(self):
        source = self.root / "song.mp3"
        source.touch()

        self.make_service().process(
            self.request(
                source=str(source),
                amt_models=(ModelWeight("magenta", 1.0),),
            )
        )

        self.assertEqual(self.transcriptions[0][2], "magenta")

    def test_saves_file_to_library_before_separating(self):
        source = self.root / "song.mp3"
        source.write_bytes(b"audio")
        service = self.make_service()

        result = service.process(
            self.request(source=str(source), save_for_later=True)
        )

        saved_path = self.paths.library_dir / source.name
        self.assertEqual(result.selected_audio, saved_path)
        self.assertEqual(self.calls[0][0], saved_path)
        self.assertTrue(saved_path.is_file())
        self.assertEqual(result.output_path.parent, saved_path.parent / "KiviPiano_output")

    def test_unsaved_youtube_source_is_temporary(self):
        downloaded_paths = []

        def download(url, output_dir):
            path = output_dir / "download.mp3"
            path.touch()
            downloaded_paths.append(path)
            return path

        service = self.make_service(downloader=download)

        result = service.process(
            self.request(source_mode="youtube", source="https://youtu.be/id")
        )

        self.assertFalse(downloaded_paths[0].parent.exists())
        self.assertEqual(self.calls[0][0], downloaded_paths[0])
        self.assertEqual(self.calls[0][1], self.paths.output_dir)
        self.assertTrue(result.output_path.is_file())
        self.assertIsNone(result.selected_audio)

    def test_saved_youtube_source_is_downloaded_to_library(self):
        def download(url, output_dir):
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / "download.mp3"
            path.touch()
            return path

        result = self.make_service(downloader=download).process(
            self.request(
                source_mode="youtube",
                source="https://youtu.be/id",
                save_for_later=True,
            )
        )

        self.assertEqual(result.selected_audio, self.paths.library_dir / "download.mp3")
        self.assertEqual(self.calls[0][0], result.selected_audio)
        self.assertEqual(
            result.output_path.parent,
            self.paths.library_dir / "KiviPiano_output",
        )

    def test_rejects_unknown_source_modes(self):
        with self.assertRaisesRegex(ValueError, "Unknown audio source mode"):
            self.make_service().process(self.request(source_mode="unknown"))

    def test_rejects_unknown_transcription_models_before_separating(self):
        with self.assertRaisesRegex(ValueError, "Unknown transcription model"):
            self.make_service().process(
                self.request(amt_models=(ModelWeight("unknown", 1.0),))
            )
        self.assertEqual(self.calls, [])

    def test_rejects_empty_model_selection(self):
        with self.assertRaisesRegex(ValueError, "Select at least one transcription model"):
            self.make_service().process(self.request(amt_models=()))

    def test_rejects_non_positive_model_weights(self):
        with self.assertRaisesRegex(ValueError, "positive number"):
            self.make_service().process(
                self.request(amt_models=(ModelWeight("basic_pitch", 0),))
            )

    def test_rejects_invalid_fusion_config(self):
        source = self.root / "song.mp3"
        source.touch()
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            self.make_service().process(
                self.request(
                    source=str(source),
                    fusion=FusionConfig(min_confidence=1.5),
                )
            )
        self.assertEqual(self.calls, [])

    def test_reuses_existing_artifacts_when_only_weights_change(self):
        source = self.root / "song.mp3"
        source.touch()

        stem_path = expected_stem_path(
            source, self.root / "KiviPiano_output", "demucs", "piano"
        )
        stem_path.parent.mkdir(parents=True, exist_ok=True)
        stem_path.touch()
        csv_path, midi_path = transcription_paths(
            stem_path, stem_path.parent, "basic_pitch"
        )
        csv_path.write_text(
            "start_time,end_time,pitch,velocity,model\n"
            "0.1,0.2,60,90,basic_pitch\n",
            encoding="utf-8",
        )
        midi_path.touch()

        def fail_separate(*_args):
            raise AssertionError("The separator should not run when the stem exists.")

        def fail_transcribe(*_args):
            raise AssertionError(
                "The transcriber should not run when its CSV and MIDI exist."
            )

        service = AudioProcessingService(
            self.paths,
            separator=fail_separate,
            transcriber=fail_transcribe,
        )

        result = service.process(
            self.request(
                source=str(source),
                amt_models=(ModelWeight("basic_pitch", 3.0),),
            )
        )

        self.assertTrue(result.output_path.is_file())
        self.assertTrue(result.midi_path.is_file())
        with result.output_path.open(encoding="utf-8", newline="") as csv_file:
            row = next(csv.DictReader(csv_file))
        self.assertEqual(row["pitch"], "60")

    def test_result_exposes_unfiltered_raw_notes(self):
        source = self.root / "song.mp3"
        source.touch()

        def separate(source_path, output_dir, model_dir, separator, stem):
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            result_path = output_path / f"{separator}_{Path(source_path).stem}_{stem}.wav"
            result_path.touch()
            return result_path

        def transcribe(audio, output_dir, model_dir, model):
            output_path = Path(output_dir)
            csv_path = output_path / f"{model}.csv"
            midi_path = output_path / f"{model}.mid"
            csv_path.write_text(
                "start_time,end_time,pitch,velocity,model\n"
                "0.0,0.02,60,90,basic_pitch\n"
                "0.1,0.3,62,90,basic_pitch\n",
                encoding="utf-8",
            )
            midi_path.touch()
            return csv_path, midi_path, 2

        service = AudioProcessingService(
            self.paths, separator=separate, transcriber=transcribe
        )
        result = service.process(self.request(source=str(source)))

        self.assertEqual(len(result.raw_notes), 2)
        with result.output_path.open(encoding="utf-8", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pitch"], "62")

    def test_fuses_selected_models_into_one_output(self):
        source = self.root / "song.mp3"
        source.touch()

        result = self.make_service().process(
            self.request(
                source=str(source),
                amt_models=(
                    ModelWeight("basic_pitch", 1.0),
                    ModelWeight("magenta", 1.0),
                ),
            )
        )

        self.assertEqual(
            [call[2] for call in self.transcriptions],
            ["basic_pitch", "magenta"],
        )
        self.assertEqual(result.output_path.name, "demucs_song_piano_fused.csv")
        with result.output_path.open(encoding="utf-8", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pitch"], "60")
        self.assertEqual(rows[0]["models"], "basic_pitch;magenta")

    def test_context_stage_refines_notes_between_fusion_and_filters(self):
        source = self.root / "song.mp3"
        source.touch()
        analyzed = []

        def separate(source_path, output_dir, model_dir, separator, stem):
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            result_path = output_path / f"{separator}_{Path(source_path).stem}_{stem}.wav"
            result_path.touch()
            return result_path

        def transcribe(audio, output_dir, model_dir, model):
            output_path = Path(output_dir)
            csv_path = output_path / f"{model}.csv"
            midi_path = output_path / f"{model}.mid"
            csv_path.write_text(
                "start_time,end_time,pitch,velocity,model\n"
                "0.03,0.50,60,90,basic_pitch\n"
                "0.25,0.40,62,90,basic_pitch\n",
                encoding="utf-8",
            )
            midi_path.touch()
            return csv_path, midi_path, 2

        def analyze(audio, output_dir, model_dir):
            analyzed.append((Path(audio).name, Path(output_dir), Path(model_dir)))
            return BeatChordAnalysis(
                (0.0, 0.5),
                120.0,
                (ChordSegment(0.0, 2.0, "C:maj", chord_pitch_classes("C:maj")),),
            )

        service = AudioProcessingService(
            self.paths, separator=separate, transcriber=transcribe, analyzer=analyze
        )
        result = service.process(
            self.request(source=str(source), context=ContextConfig(enabled=True))
        )

        self.assertEqual(len(analyzed), 1)
        # The C note (0.03s) is snapped onto the beat; the off-beat D (0.25s)
        # is not a C-major chord tone, so the context stage drops it.
        with result.output_path.open(encoding="utf-8", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pitch"], "60")
        self.assertEqual(float(rows[0]["start_time"]), 0.0)

    def test_context_stage_is_skipped_when_disabled(self):
        source = self.root / "song.mp3"
        source.touch()

        def analyze(*_args):
            raise AssertionError("The analyzer should not run when disabled.")

        service = self.make_service()
        service._analyzer = analyze
        result = service.process(self.request(source=str(source)))
        self.assertTrue(result.output_path.is_file())


if __name__ == "__main__":
    unittest.main()
