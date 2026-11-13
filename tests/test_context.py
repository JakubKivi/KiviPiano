import tempfile
import unittest
from pathlib import Path

from kivipiano.fusion import FusedNote
from kivipiano.musical_context import (
    BeatChordAnalysis,
    ChordSegment,
    ContextConfig,
    _tempo_from_beats,
    chord_pitch_classes,
    read_context,
    refine_notes,
    write_context,
)


def note(
    start: float,
    end: float,
    pitch: int,
    velocity: int = 90,
    confidence: float = 1.0,
    models: tuple[str, ...] = ("m",),
) -> FusedNote:
    return FusedNote(start, end, pitch, velocity, confidence, models)


def chord(start: float, end: float, label: str) -> ChordSegment:
    return ChordSegment(start, end, label, chord_pitch_classes(label))


class ChordLabelTests(unittest.TestCase):
    def test_major_chord_pitch_classes(self):
        self.assertEqual(chord_pitch_classes("C:maj"), frozenset({0, 4, 7}))

    def test_sharp_minor_chord_pitch_classes(self):
        self.assertEqual(chord_pitch_classes("F#:min"), frozenset({6, 9, 1}))

    def test_no_chord_is_empty(self):
        self.assertEqual(chord_pitch_classes("N"), frozenset())

    def test_unknown_labels_are_empty(self):
        self.assertEqual(chord_pitch_classes(""), frozenset())
        self.assertEqual(chord_pitch_classes("C:dim"), frozenset())


class ContextConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        ContextConfig().validate()

    def test_negative_tolerances_are_rejected(self):
        with self.assertRaises(ValueError):
            ContextConfig(snap_tolerance=0).validate()
        with self.assertRaises(ValueError):
            ContextConfig(off_beat_tolerance=-1).validate()


class RefineNotesTests(unittest.TestCase):
    def _analysis(self, beats=(), chords=(), tempo=120.0) -> BeatChordAnalysis:
        return BeatChordAnalysis(tuple(beats), tempo, tuple(chords))

    def test_snaps_note_onset_to_nearest_beat_preserving_duration(self):
        analysis = self._analysis(beats=(0.0, 0.5, 1.0))
        notes = [note(0.03, 0.53, 60), note(0.47, 0.97, 62)]
        refined = refine_notes(notes, analysis, ContextConfig())
        self.assertEqual(
            [(n.start, n.end) for n in refined], [(0.0, 0.5), (0.5, 1.0)]
        )

    def test_leaves_notes_far_from_any_beat_unsnapped(self):
        analysis = self._analysis(beats=(0.0, 0.5, 1.0))
        refined = refine_notes([note(0.25, 0.6, 60)], analysis, ContextConfig())
        self.assertEqual(refined[0].start, 0.25)

    def test_drops_off_beat_non_chord_note(self):
        # C major sounds throughout; pitch 62 (D) is not a chord tone.
        analysis = self._analysis(beats=(0.0, 0.5), chords=[chord(0.0, 2.0, "C:maj")])
        refined = refine_notes([note(0.25, 0.6, 62)], analysis, ContextConfig())
        self.assertEqual(refined, [])

    def test_keeps_off_beat_chord_tone(self):
        analysis = self._analysis(beats=(0.0, 0.5), chords=[chord(0.0, 2.0, "C:maj")])
        refined = refine_notes([note(0.25, 0.6, 64)], analysis, ContextConfig())
        self.assertEqual([n.pitch for n in refined], [64])

    def test_keeps_on_beat_non_chord_note(self):
        analysis = self._analysis(beats=(0.0, 0.5), chords=[chord(0.0, 2.0, "C:maj")])
        refined = refine_notes([note(0.02, 0.4, 62)], analysis, ContextConfig())
        self.assertEqual([n.pitch for n in refined], [62])

    def test_missing_chord_evidence_never_drops_notes(self):
        analysis = self._analysis(beats=(0.0, 0.5), chords=[chord(0.0, 2.0, "N")])
        refined = refine_notes([note(0.25, 0.6, 62)], analysis, ContextConfig())
        self.assertEqual([n.pitch for n in refined], [62])

    def test_missing_beats_never_drops_notes(self):
        analysis = self._analysis(beats=(), chords=[chord(0.0, 2.0, "C:maj")])
        refined = refine_notes([note(0.25, 0.6, 62)], analysis, ContextConfig())
        self.assertEqual([n.pitch for n in refined], [62])

    def test_disabled_steps_leave_notes_unchanged(self):
        analysis = self._analysis(beats=(0.0, 0.5), chords=[chord(0.0, 2.0, "C:maj")])
        config = ContextConfig(beat_snap=False, chord_filter=False)
        notes = [note(0.03, 0.53, 60), note(0.25, 0.6, 62)]
        refined = refine_notes(notes, analysis, config)
        self.assertEqual([n.start for n in refined], [0.03, 0.25])
        self.assertEqual(len(refined), 2)

    def test_refinement_orders_notes(self):
        analysis = self._analysis(beats=(0.0, 0.5, 1.0))
        notes = [note(0.47, 0.97, 62), note(0.03, 0.53, 60)]
        refined = refine_notes(notes, analysis, ContextConfig())
        self.assertEqual([n.start for n in refined], [0.0, 0.5])


class ContextSerializationTests(unittest.TestCase):
    def test_write_and_read_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "analysis.json"
            analysis = BeatChordAnalysis(
                (0.0, 0.5, 1.0),
                120.0,
                (chord(0.0, 2.0, "C:maj"), chord(2.0, 4.0, "A:min")),
            )
            write_context(analysis, path)
            loaded = read_context(path)
        self.assertEqual(loaded.beats, (0.0, 0.5, 1.0))
        self.assertEqual(loaded.tempo, 120.0)
        self.assertEqual(loaded.chords[0].label, "C:maj")
        self.assertEqual(loaded.chords[0].pitch_classes, frozenset({0, 4, 7}))
        self.assertEqual(loaded.chords[1].label, "A:min")

    def test_read_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_context(Path(tempfile.gettempdir()) / "does-not-exist.json")


class TempoTests(unittest.TestCase):
    def test_tempo_from_evenly_spaced_beats(self):
        self.assertEqual(_tempo_from_beats((0.0, 0.5, 1.0, 1.5)), 120.0)

    def test_tempo_from_too_few_beats_is_zero(self):
        self.assertEqual(_tempo_from_beats(()), 0.0)
        self.assertEqual(_tempo_from_beats((0.0,)), 0.0)


if __name__ == "__main__":
    unittest.main()

