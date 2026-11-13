import unittest

from kivipiano.filters import (
    DurationGate,
    FilterConfig,
    NoteMerger,
    OvertoneSuppressor,
    PitchBandPass,
    PolyphonyLimiter,
    VelocityGate,
    apply_filters,
    build_filter_pipeline,
    create_note_filter,
)
from kivipiano.fusion import FusedNote


def note(
    start: float,
    end: float,
    pitch: int,
    velocity: int,
    confidence: float = 1.0,
    models: tuple[str, ...] = ("m",),
) -> FusedNote:
    return FusedNote(start, end, pitch, velocity, confidence, models)


class NoteFilterTests(unittest.TestCase):
    def test_duration_gate_drops_short_notes(self):
        gate = DurationGate(min_duration=0.05)
        notes = [note(0.0, 0.02, 60, 80), note(0.0, 0.1, 62, 80)]
        self.assertEqual([n.pitch for n in gate.apply(notes)], [62])

    def test_velocity_gate_drops_bottom_percentile(self):
        gate = VelocityGate(percentile=20.0)
        notes = [
            note(0, 1, 60, 10),
            note(0, 1, 62, 20),
            note(0, 1, 64, 30),
            note(0, 1, 65, 40),
            note(0, 1, 67, 100),
        ]
        self.assertEqual([n.velocity for n in gate.apply(notes)], [20, 30, 40, 100])

    def test_pitch_band_pass_keeps_only_in_range_pitches(self):
        band = PitchBandPass(min_pitch=28, max_pitch=96)
        notes = [note(0, 1, 20, 80), note(0, 1, 60, 80), note(0, 1, 100, 80)]
        self.assertEqual([n.pitch for n in band.apply(notes)], [60])

    def test_merger_stitches_close_same_pitch_notes(self):
        merger = NoteMerger(max_gap=0.04)
        notes = [
            note(0.0, 0.1, 60, 80),
            note(0.12, 0.2, 60, 90),
            note(0.3, 0.4, 60, 70),
        ]
        merged = merger.apply(notes)
        self.assertEqual(len(merged), 2)
        self.assertEqual((merged[0].start, merged[0].end), (0.0, 0.2))
        self.assertEqual(merged[0].velocity, 90)
        self.assertEqual((merged[1].start, merged[1].end), (0.3, 0.4))

    def test_merger_unions_models_and_keeps_max_confidence(self):
        merger = NoteMerger(max_gap=0.04)
        a = FusedNote(0.0, 0.1, 60, 80, 0.5, ("x",))
        b = FusedNote(0.12, 0.2, 60, 90, 0.9, ("y",))
        merged = merger.apply([a, b])
        self.assertEqual(merged[0].models, ("x", "y"))
        self.assertEqual(merged[0].confidence, 0.9)

    def test_polyphony_limiter_keeps_loudest_per_window(self):
        limiter = PolyphonyLimiter(window=0.05, max_notes=2)
        notes = [
            note(0.00, 0.1, 60, 50),
            note(0.01, 0.1, 62, 90),
            note(0.02, 0.1, 64, 70),
            note(0.03, 0.1, 65, 10),
            note(0.10, 0.2, 67, 80),
        ]
        self.assertEqual([n.pitch for n in limiter.apply(notes)], [62, 64, 67])

    def test_overtone_suppressor_removes_quiet_octave_and_fifth(self):
        suppressor = OvertoneSuppressor()
        notes = [
            note(0.0, 1.0, 60, 80),
            note(0.0, 1.0, 72, 30),
            note(0.0, 1.0, 79, 30),
        ]
        self.assertEqual([n.pitch for n in suppressor.apply(notes)], [60])

    def test_overtone_suppressor_keeps_loud_overtone(self):
        suppressor = OvertoneSuppressor()
        notes = [
            note(0.0, 1.0, 60, 80),
            note(0.0, 1.0, 72, 60),
        ]
        self.assertEqual(sorted(n.pitch for n in suppressor.apply(notes)), [60, 72])

    def test_overtone_suppressor_ignores_non_overtone_intervals(self):
        suppressor = OvertoneSuppressor()
        notes = [
            note(0.0, 1.0, 60, 80),
            note(0.0, 1.0, 65, 30),
        ]
        self.assertEqual(sorted(n.pitch for n in suppressor.apply(notes)), [60, 65])

    def test_overtone_suppressor_requires_overlap(self):
        suppressor = OvertoneSuppressor()
        notes = [
            note(0.0, 0.5, 60, 80),
            note(0.6, 1.0, 72, 30),
        ]
        self.assertEqual(sorted(n.pitch for n in suppressor.apply(notes)), [60, 72])

    def test_filter_registry(self):
        self.assertEqual(type(create_note_filter("duration_gate")).__name__, "DurationGate")
        with self.assertRaisesRegex(ValueError, "Unknown note filter"):
            create_note_filter("missing")

    def test_filter_config_validation(self):
        FilterConfig().validate()
        with self.assertRaises(ValueError):
            FilterConfig(min_duration=0).validate()
        with self.assertRaises(ValueError):
            FilterConfig(velocity_percentile=150).validate()
        with self.assertRaises(ValueError):
            FilterConfig(min_pitch=100, max_pitch=50).validate()
        with self.assertRaises(ValueError):
            FilterConfig(merge_gap=-1).validate()
        with self.assertRaises(ValueError):
            FilterConfig(polyphony_max=0).validate()
        with self.assertRaises(ValueError):
            FilterConfig(overtone_ratio=1.5).validate()

    def test_disabled_filters_are_skipped(self):
        all_off = FilterConfig(
            duration_gate=False,
            velocity_gate=False,
            pitch_band_pass=False,
            merge_notes=False,
            polyphony_limit=False,
            overtone_suppression=False,
        )
        notes = [note(0.0, 0.02, 20, 10), note(0.0, 0.1, 100, 80)]
        self.assertEqual(apply_filters(notes, all_off), notes)

    def test_build_filter_pipeline_respects_config(self):
        self.assertEqual(len(build_filter_pipeline(FilterConfig())._filters), 6)
        partial = build_filter_pipeline(
            FilterConfig(pitch_band_pass=False, overtone_suppression=False)
        )
        self.assertEqual(len(partial._filters), 4)

    def test_apply_filters_cleans_artifacts(self):
        notes = [
            note(0.00, 0.01, 60, 80),  # too short
            note(0.10, 0.20, 20, 80),  # out of pitch range
            note(0.10, 0.20, 60, 90),
            note(0.10, 0.20, 72, 30),  # quiet octave overtone
        ]
        kept = apply_filters(notes, FilterConfig())
        self.assertEqual([n.pitch for n in kept], [60])


if __name__ == "__main__":
    unittest.main()
