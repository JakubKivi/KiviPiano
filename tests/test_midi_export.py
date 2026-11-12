import tempfile
import unittest
from pathlib import Path

from kivipiano.fusion import FusedNote
from kivipiano.midi_export import (
    ExportSettings,
    LedColors,
    LoggingTransport,
    build_device_events,
    midi_note_name,
    note_hand,
    notes_duration,
    split_hands,
    write_tempo_midi,
)


def note(start, end, pitch, velocity=80):
    return FusedNote(start, end, pitch, velocity, 1.0, ("basic_pitch",))


class MidiExportTests(unittest.TestCase):
    def test_note_hand_split_at_middle_c(self):
        self.assertEqual(note_hand(59), "left")
        self.assertEqual(note_hand(60), "right")
        self.assertEqual(note_hand(71, split_pitch=72), "left")

    def test_split_hands_groups_notes(self):
        left, right = split_hands([note(0, 1, 55), note(0, 1, 64), note(0, 1, 60)])
        self.assertEqual([n.pitch for n in left], [55])
        self.assertEqual([n.pitch for n in right], [64, 60])

    def test_midi_note_name(self):
        self.assertEqual(midi_note_name(60), "C4")
        self.assertEqual(midi_note_name(61), "C#4")
        self.assertEqual(midi_note_name(21), "A0")

    def test_notes_duration(self):
        self.assertEqual(notes_duration([note(0, 1.5, 60), note(2, 3, 64)]), 3.0)
        self.assertEqual(notes_duration([]), 0.0)

    def test_write_tempo_midi_creates_two_tracks(self):
        settings = ExportSettings(bpm=90, split_pitch=60)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "out.mid"
            write_tempo_midi([note(0, 1, 55), note(0, 1, 64)], path, settings)
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 0)

            import pretty_midi

            midi = pretty_midi.PrettyMIDI(str(path))
            self.assertEqual(len(midi.instruments), 2)
            self.assertEqual(midi.instruments[0].name, "Right hand")
            self.assertEqual(midi.instruments[1].name, "Left hand")

    def test_build_events_colors_by_hand(self):
        settings = ExportSettings(colors=LedColors("#A", "#B", "#C", "#D"))
        events = build_device_events(
            [note(1.0, 2.0, 55), note(1.0, 2.0, 64)], settings, prepare_ms=500
        )
        by_state = {(e.pitch, e.state): e for e in events}
        self.assertEqual(by_state[(55, "prepare")].color, "#A")
        self.assertEqual(by_state[(55, "click")].color, "#B")
        self.assertEqual(by_state[(64, "prepare")].color, "#C")
        self.assertEqual(by_state[(64, "click")].color, "#D")

    def test_build_events_prepare_timing(self):
        events = build_device_events([note(1.0, 2.0, 60)], ExportSettings(), prepare_ms=500)
        self.assertEqual(len(events), 2)
        prepare = next(e for e in events if e.state == "prepare")
        click = next(e for e in events if e.state == "click")
        self.assertAlmostEqual(click.time, 1.0)
        self.assertAlmostEqual(prepare.time, 0.5)

    def test_build_events_loop_filters_and_rebases(self):
        notes = [note(1.0, 2.0, 60), note(5.0, 6.0, 62), note(9.0, 10.0, 64)]
        events = build_device_events(notes, ExportSettings(), prepare_ms=0, loop=(4.0, 8.0))
        self.assertEqual({e.pitch for e in events}, {62})
        click = next(e for e in events if e.state == "click")
        self.assertAlmostEqual(click.time, 1.0)

    def test_build_events_rejects_invalid_loop(self):
        with self.assertRaisesRegex(ValueError, "end after it starts"):
            build_device_events([note(1, 2, 60)], ExportSettings(), loop=(5.0, 5.0))

    def test_logging_transport_records_events(self):
        transport = LoggingTransport()
        events = build_device_events([note(1, 2, 60)], ExportSettings(), prepare_ms=0)
        transport.send(events)
        self.assertEqual(transport.sent, events)


if __name__ == "__main__":
    unittest.main()
