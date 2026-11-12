import tempfile
import unittest
from pathlib import Path

from kivipiano.fusion import (
    FusedNote,
    Note,
    create_fusion_strategy,
    fuse_notes,
    read_fused_csv,
    read_notes_csv,
    write_fused_csv,
    write_fused_midi,
)


class NoteFusionTests(unittest.TestCase):
    def test_identical_notes_fuse_with_full_confidence(self):
        fused = fuse_notes(
            {
                "a": [Note(1.0, 2.0, 60, 80, "a")],
                "b": [Note(1.0, 2.0, 60, 90, "b")],
            },
            {"a": 1.0, "b": 1.0},
        )

        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0].pitch, 60)
        self.assertEqual(fused[0].velocity, 85)
        self.assertEqual(fused[0].confidence, 1.0)
        self.assertEqual(fused[0].models, ("a", "b"))

    def test_weights_bias_the_aggregated_times(self):
        fused = fuse_notes(
            {
                "strong": [Note(1.0, 2.0, 60, 80, "strong")],
                "weak": [Note(1.4, 2.4, 60, 100, "weak")],
            },
            {"strong": 3.0, "weak": 1.0},
        )

        self.assertEqual(len(fused), 1)
        self.assertAlmostEqual(fused[0].start, 1.1)
        self.assertAlmostEqual(fused[0].end, 2.1)
        self.assertEqual(fused[0].velocity, 85)

    def test_weights_are_normalized(self):
        fused = fuse_notes(
            {"a": [Note(0.0, 1.0, 60, 80, "a")]},
            {"a": 42.0},
        )
        self.assertEqual(fused[0].confidence, 1.0)

    def test_different_pitches_stay_separate(self):
        fused = fuse_notes(
            {
                "a": [
                    Note(0.0, 1.0, 60, 80, "a"),
                    Note(0.0, 1.0, 64, 80, "a"),
                ]
            },
            {"a": 1.0},
        )
        self.assertEqual({note.pitch for note in fused}, {60, 64})

    def test_non_overlapping_same_pitch_notes_stay_separate(self):
        fused = fuse_notes(
            {
                "a": [
                    Note(0.0, 1.0, 60, 80, "a"),
                    Note(1.1, 2.0, 60, 80, "a"),
                ]
            },
            {"a": 1.0},
        )
        self.assertEqual(len(fused), 2)

    def test_note_from_low_weight_model_has_partial_confidence(self):
        fused = fuse_notes(
            {
                "a": [Note(1.0, 2.0, 60, 80, "a")],
                "b": [Note(3.0, 4.0, 67, 80, "b")],
            },
            {"a": 3.0, "b": 1.0},
        )
        by_pitch = {note.pitch: note for note in fused}
        self.assertAlmostEqual(by_pitch[60].confidence, 0.75)
        self.assertAlmostEqual(by_pitch[67].confidence, 0.25)

    def test_rejects_non_positive_weights(self):
        with self.assertRaisesRegex(ValueError, "positive weight"):
            fuse_notes({"a": [Note(0.0, 1.0, 60, 80, "a")]}, {"a": 0.0})

    def test_fusion_strategy_registry(self):
        strategy = create_fusion_strategy("weighted_vote")
        self.assertEqual(type(strategy).__name__, "WeightedVoteFusion")
        with self.assertRaisesRegex(ValueError, "Unknown fusion strategy"):
            create_fusion_strategy("missing")

    def test_read_notes_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "model.csv"
            csv_path.write_text(
                "start_time,end_time,pitch,velocity,model\n"
                "0.5,1.5,60,80,basic_pitch\n"
                "2.0,3.0,64,100,magenta\n",
                encoding="utf-8",
            )
            notes = read_notes_csv(csv_path)
            self.assertEqual([note.pitch for note in notes], [60, 64])
            self.assertEqual(notes[0].model, "basic_pitch")
            self.assertEqual(notes[1].velocity, 100)

    def test_read_fused_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "fused.csv"
            csv_path.write_text(
                "start_time,end_time,pitch,velocity,confidence,models\n"
                "0.5,1.5,60,80,0.75,basic_pitch;magenta\n"
                "2.0,3.0,64,100,1.0,basic_pitch\n",
                encoding="utf-8",
            )
            notes = read_fused_csv(csv_path)
            self.assertEqual([note.pitch for note in notes], [60, 64])
            self.assertAlmostEqual(notes[0].confidence, 0.75)
            self.assertEqual(notes[0].models, ("basic_pitch", "magenta"))
            self.assertEqual(notes[1].velocity, 100)

    def test_write_fused_csv_and_midi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fused = [FusedNote(1.0, 2.0, 60, 80, 0.5, ("a", "b"))]
            csv_path = root / "fused.csv"
            midi_path = root / "fused.mid"
            write_fused_csv(fused, csv_path)
            write_fused_midi(fused, midi_path)
            self.assertTrue(csv_path.is_file())
            self.assertGreater(midi_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
