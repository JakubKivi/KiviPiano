"""MIDI export, hand assignment, and edge-device event scheduling.

Stage 5 ("MIDI") lets the user download the fused transcription with an
explicit tempo and a right/left hand split, and stage 6 ("Device") turns the
same notes into timed LED events for an edge device. Both stages share the
helpers in this module, which are deliberately UI-free so they can be
unit-tested without a display.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from kivipiano.fusion import FusedNote

DEFAULT_BPM = 120
DEFAULT_SPLIT_PITCH = 60  # MIDI note number of middle C (C4)
DEFAULT_PREPARE_MS = 500

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


@dataclass(frozen=True)
class LedColors:
    """LED colours for each hand: one for prepare and one for the click."""

    left_prepare: str
    left_click: str
    right_prepare: str
    right_click: str

    @classmethod
    def default(cls) -> "LedColors":
        return cls(
            left_prepare="#7dd3fc",
            left_click="#0284c7",
            right_prepare="#fcd34d",
            right_click="#d97706",
        )


@dataclass(frozen=True)
class ExportSettings:
    """Tempo and colour settings shared by the MIDI and Device stages."""

    bpm: int = DEFAULT_BPM
    split_pitch: int = DEFAULT_SPLIT_PITCH
    colors: LedColors = field(default_factory=LedColors.default)


@dataclass(frozen=True)
class DeviceEvent:
    """A single timed LED event destined for the edge device."""

    time: float
    pitch: int
    hand: str
    state: str  # "prepare" or "click"
    color: str
    velocity: int


class DeviceTransport(Protocol):
    """Delivers prepared events to an edge device."""

    def send(self, events: Sequence[DeviceEvent]) -> None: ...


class LoggingTransport:
    """Preview transport that records events instead of talking to hardware."""

    def __init__(self) -> None:
        self.sent: list[DeviceEvent] = []

    def send(self, events: Sequence[DeviceEvent]) -> None:
        self.sent.extend(events)


def midi_note_name(pitch: int) -> str:
    """Return the scientific name of a MIDI pitch, e.g. ``60`` -> ``"C4"``."""
    return f"{_NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def note_hand(pitch: int, split_pitch: int = DEFAULT_SPLIT_PITCH) -> str:
    """Return ``"right"`` for notes at or above the split point, else ``"left"``."""
    return "right" if pitch >= split_pitch else "left"


def split_hands(
    notes: Sequence[FusedNote], split_pitch: int = DEFAULT_SPLIT_PITCH
) -> tuple[list[FusedNote], list[FusedNote]]:
    """Return ``(left_hand, right_hand)`` note lists."""
    left = [note for note in notes if note_hand(note.pitch, split_pitch) == "left"]
    right = [note for note in notes if note_hand(note.pitch, split_pitch) == "right"]
    return left, right


def notes_duration(notes: Sequence[FusedNote]) -> float:
    """Return the end time of the latest note, or ``0`` for an empty set."""
    return max((note.end for note in notes), default=0.0)


def write_tempo_midi(
    notes: Sequence[FusedNote],
    midi_path: str | Path,
    settings: ExportSettings,
) -> None:
    """Write ``notes`` as a two-track MIDI file with ``settings`` applied.

    The right hand is written to the first instrument and the left hand to the
    second; the file's initial tempo is set to ``settings.bpm``.
    """
    try:
        import pretty_midi
    except ImportError as exc:
        raise RuntimeError(
            "pretty-midi is unavailable. Reinstall the project requirements."
        ) from exc

    if settings.bpm <= 0:
        raise ValueError("Tempo must be a positive number of beats per minute.")

    midi = pretty_midi.PrettyMIDI(initial_tempo=float(settings.bpm))
    right = pretty_midi.Instrument(program=0, name="Right hand")
    left = pretty_midi.Instrument(program=0, name="Left hand")
    for note in notes:
        instrument = (
            right if note_hand(note.pitch, settings.split_pitch) == "right" else left
        )
        instrument.notes.append(
            pretty_midi.Note(
                velocity=max(0, min(127, note.velocity)),
                pitch=max(0, min(127, note.pitch)),
                start=max(0.0, note.start),
                end=max(note.start, note.end),
            )
        )
    if right.notes:
        midi.instruments.append(right)
    if left.notes:
        midi.instruments.append(left)
    midi.write(str(midi_path))


def build_device_events(
    notes: Sequence[FusedNote],
    settings: ExportSettings,
    *,
    prepare_ms: int = DEFAULT_PREPARE_MS,
    loop: tuple[float, float] | None = None,
) -> list[DeviceEvent]:
    """Build the timed LED events for ``notes``.

    Every note produces a ``"prepare"`` event ``prepare_ms`` before its onset
    (in the hand's prepare colour) and a ``"click"`` event at its onset (in the
    hand's click colour). When ``loop`` is given, only notes that start inside
    the range are kept and their times are re-based so the loop starts at zero.
    """
    prepare = max(0, prepare_ms) / 1000.0
    offset = 0.0
    if loop is not None:
        loop_start, loop_end = loop
        if loop_end <= loop_start:
            raise ValueError("The loop must end after it starts.")
        offset = loop_start

    events: list[DeviceEvent] = []
    for note in notes:
        if loop is not None:
            loop_start, loop_end = loop
            if note.start < loop_start or note.start >= loop_end:
                continue
        hand = note_hand(note.pitch, settings.split_pitch)
        if hand == "left":
            prepare_color = settings.colors.left_prepare
            click_color = settings.colors.left_click
        else:
            prepare_color = settings.colors.right_prepare
            click_color = settings.colors.right_click

        click_time = note.start - offset
        events.append(
            DeviceEvent(
                time=max(0.0, click_time - prepare),
                pitch=note.pitch,
                hand=hand,
                state="prepare",
                color=prepare_color,
                velocity=note.velocity,
            )
        )
        events.append(
            DeviceEvent(
                time=click_time,
                pitch=note.pitch,
                hand=hand,
                state="click",
                color=click_color,
                velocity=note.velocity,
            )
        )
    events.sort(
        key=lambda event: (event.time, 0 if event.state == "prepare" else 1, event.pitch)
    )
    return events

