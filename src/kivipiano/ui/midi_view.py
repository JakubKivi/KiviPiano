"""Canvas-based piano-roll visualization for the fused MIDI notes."""

import tkinter as tk
from typing import Callable, Sequence

import customtkinter as ctk

from kivipiano.fusion import FusedNote
from kivipiano.midi_export import ExportSettings, midi_note_name, note_hand

_LEFT_MARGIN = 34
_RIGHT_MARGIN = 6
_TOP_MARGIN = 6
_BOTTOM_MARGIN = 22


class PianoRollView(ctk.CTkFrame):
    """Draws fused notes as a piano roll, optionally with drag selection."""

    def __init__(
        self,
        master,
        *,
        height: int = 180,
        selectable: bool = False,
        on_selection: Callable[[tuple[float, float]], None] | None = None,
    ) -> None:
        super().__init__(master, corner_radius=8)
        self._notes: list[FusedNote] = []
        self._settings = ExportSettings()
        self._selectable = selectable
        self._on_selection = on_selection
        self._selection: tuple[float, float] | None = None
        self._drag_anchor: float | None = None

        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        if selectable:
            self.canvas.bind("<ButtonPress-1>", self._on_press)
            self.canvas.bind("<B1-Motion>", self._on_drag)
            self.canvas.bind("<ButtonRelease-1>", self._on_release)

    # -- public API ---------------------------------------------------------

    def set_notes(self, notes: Sequence[FusedNote], settings: ExportSettings) -> None:
        self._notes = list(notes)
        self._settings = settings
        self.redraw()

    def set_settings(self, settings: ExportSettings) -> None:
        self._settings = settings
        self.redraw()

    def set_selection(self, selection: tuple[float, float] | None) -> None:
        self._selection = selection
        self.redraw()

    def selection(self) -> tuple[float, float] | None:
        return self._selection

    # -- drawing ------------------------------------------------------------

    def _palette(self) -> dict[str, str]:
        if ctk.get_appearance_mode().lower() == "dark":
            return {
                "bg": "#1f1f1f",
                "grid": "#3a3a3a",
                "text": "#e4e4e7",
                "label": "#71717a",
                "selection": "#3b82f6",
            }
        return {
            "bg": "#ffffff",
            "grid": "#e4e4e7",
            "text": "#3f3f46",
            "label": "#71717a",
            "selection": "#93c5fd",
        }

    def _plot_geometry(self) -> tuple[int, int, int, int, float, float]:
        width = max(self.canvas.winfo_width(), 120)
        height = max(self.canvas.winfo_height(), 60)
        plot_w = width - _LEFT_MARGIN - _RIGHT_MARGIN
        plot_h = height - _TOP_MARGIN - _BOTTOM_MARGIN
        t0, t1 = self._time_range()
        return _LEFT_MARGIN, _TOP_MARGIN, plot_w, plot_h, t0, t1

    def _time_range(self) -> tuple[float, float]:
        if not self._notes:
            return (0.0, 1.0)
        end = max(note.end for note in self._notes)
        return (0.0, end if end > 0 else 1.0)

    def _pitch_range(self) -> tuple[int, int]:
        if not self._notes:
            return (36, 84)
        low = min(note.pitch for note in self._notes) - 2
        high = max(note.pitch for note in self._notes) + 2
        low = max(0, low)
        high = min(127, high)
        if high - low < 12:
            center = (low + high) // 2
            low = max(0, center - 6)
            high = min(127, center + 6)
        return low, high

    def redraw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        left, top, plot_w, plot_h, t0, t1 = self._plot_geometry()
        if plot_w <= 0 or plot_h <= 0:
            return
        pal = self._palette()
        canvas.configure(bg=pal["bg"])
        p_lo, p_hi = self._pitch_range()

        def x(t: float) -> float:
            return left + (t - t0) / (t1 - t0) * plot_w

        def y(pitch: int) -> float:
            return top + (p_hi - pitch) / (p_hi - p_lo) * plot_h

        for pitch in range(p_lo, p_hi + 1):
            if pitch % 12 == 0:
                yy = y(pitch)
                canvas.create_line(left, yy, left + plot_w, yy, fill=pal["grid"])
                canvas.create_text(
                    2,
                    yy,
                    text=midi_note_name(pitch),
                    anchor="w",
                    fill=pal["text"],
                    font=("TkDefaultFont", 8),
                )

        bar_h = max(3, min(10, plot_h / (p_hi - p_lo + 1) * 0.7))
        for note in self._notes:
            hand = note_hand(note.pitch, self._settings.split_pitch)
            if hand == "right":
                fill = self._settings.colors.right_click
                outline = self._settings.colors.right_prepare
            else:
                fill = self._settings.colors.left_click
                outline = self._settings.colors.left_prepare
            x0 = x(max(note.start, t0))
            x1 = x(min(note.end, t1))
            if x1 - x0 < 2:
                x1 = x0 + 2
            yy = y(note.pitch)
            canvas.create_rectangle(
                x0, yy - bar_h / 2, x1, yy + bar_h / 2,
                fill=fill, outline=outline, width=1,
            )

        if self._selection is not None:
            s0, s1 = self._selection
            if s1 > s0:
                canvas.create_rectangle(
                    x(max(s0, t0)), top, x(min(s1, t1)), top + plot_h,
                    fill=pal["selection"], stipple="gray50", outline="",
                )

        ticks = 6
        for i in range(ticks + 1):
            t = t0 + (t1 - t0) * i / ticks
            xx = x(t)
            canvas.create_line(
                xx, top + plot_h, xx, top + plot_h + 4, fill=pal["label"]
            )
            canvas.create_text(
                xx,
                top + plot_h + 6,
                text=f"{t:.1f}s",
                anchor="n",
                fill=pal["label"],
                font=("TkDefaultFont", 8),
            )

    # -- selection ----------------------------------------------------------

    def _time_at(self, px: float) -> float:
        left, _top, plot_w, _ph, t0, t1 = self._plot_geometry()
        if plot_w <= 0:
            return t0
        frac = (px - left) / plot_w
        frac = max(0.0, min(1.0, frac))
        return t0 + frac * (t1 - t0)

    def _on_press(self, event) -> None:
        anchor = self._time_at(event.x)
        self._drag_anchor = anchor
        self._selection = (anchor, anchor)
        self.redraw()

    def _on_drag(self, event) -> None:
        if self._drag_anchor is None:
            return
        t = self._time_at(event.x)
        self._selection = (min(self._drag_anchor, t), max(self._drag_anchor, t))
        self.redraw()

    def _on_release(self, event) -> None:
        t = self._time_at(event.x)
        if self._drag_anchor is not None:
            self._selection = (min(self._drag_anchor, t), max(self._drag_anchor, t))
        self._drag_anchor = None
        self.redraw()
        if self._selection is not None and self._on_selection is not None:
            self._on_selection(self._selection)

