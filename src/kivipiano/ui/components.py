from pathlib import Path
from tkinter import BooleanVar, DoubleVar, IntVar, StringVar, colorchooser
from typing import Callable, Sequence

import customtkinter as ctk

from kivipiano.fusion import FusedNote
from kivipiano.midi_export import (
    ExportSettings,
    LedColors,
    midi_note_name,
    notes_duration,
)
from kivipiano.separation import SEPARATOR_STEMS
from kivipiano.transcription import AMT_MODELS
from kivipiano.ui.midi_view import PianoRollView


class InputPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_change: Callable[..., None],
        on_browse: Callable[[], None],
        on_refresh: Callable[[], None],
    ) -> None:
        super().__init__(master, corner_radius=12)
        self.youtube_url = StringVar()
        self.file_path = StringVar()
        self.save_youtube = ctk.BooleanVar(value=True)
        self.save_file = ctk.BooleanVar(value=False)
        self.library_selection = StringVar()
        self.library_files: dict[str, Path] = {}

        self.tabs = ctk.CTkTabview(self, height=175, command=on_change)
        self.tabs.pack(fill="x", padx=12, pady=12)
        youtube_tab = self.tabs.add("YouTube")
        file_tab = self.tabs.add("Audio File")
        library_tab = self.tabs.add("Saved Files")

        self.youtube_entry = ctk.CTkEntry(
            youtube_tab,
            textvariable=self.youtube_url,
            placeholder_text="https://www.youtube.com/watch?v=...",
            height=38,
        )
        self.youtube_entry.pack(fill="x", padx=12, pady=(17, 10))
        ctk.CTkCheckBox(
            youtube_tab,
            text="Save downloaded MP3 to the KiviPiano library",
            variable=self.save_youtube,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        file_row = ctk.CTkFrame(file_tab, fg_color="transparent")
        file_row.pack(fill="x", padx=12, pady=(17, 8))
        ctk.CTkEntry(
            file_row,
            textvariable=self.file_path,
            state="readonly",
            placeholder_text="No file selected",
            height=38,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(
            file_row,
            text="Browse",
            command=on_browse,
            width=115,
            height=38,
        ).pack(side="right")
        ctk.CTkCheckBox(
            file_tab,
            text="Save a copy to the KiviPiano library",
            variable=self.save_file,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        ctk.CTkLabel(
            library_tab,
            text="Select a previously saved audio file",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(16, 8))
        self.library_combo = ctk.CTkComboBox(
            library_tab,
            variable=self.library_selection,
            values=["No saved audio files"],
            state="readonly",
        )
        self.library_combo.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(
            library_tab,
            text="Refresh saved files",
            command=on_refresh,
            width=150,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        for variable in (self.youtube_url, self.file_path, self.library_selection):
            variable.trace_add("write", on_change)

    @property
    def selected_tab(self) -> str:
        return self.tabs.get()

    def set_library_files(self, files: Sequence[Path]) -> None:
        self.library_files = {path.name: path for path in files}
        names = list(self.library_files)
        if names:
            self.library_combo.configure(values=names)
            if self.library_selection.get() not in self.library_files:
                self.library_selection.set(names[0])
        else:
            self.library_combo.configure(values=["No saved audio files"])
            self.library_selection.set("No saved audio files")

    def set_library_unavailable(self) -> None:
        self.library_files = {}
        self.library_selection.set("Library unavailable")
        self.library_combo.configure(values=["Library unavailable"])


class SeparatorPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_change: Callable[[], None],
        available: dict[str, bool] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        available = available or {"demucs": True, "spleeter": True}
        demucs_ok = bool(available.get("demucs", True))
        spleeter_ok = bool(available.get("spleeter", True))

        self.use_demucs = ctk.BooleanVar(value=demucs_ok)
        self.demucs_stem = ctk.StringVar(value="Piano")
        self.use_spleeter = ctk.BooleanVar(value=not demucs_ok and spleeter_ok)
        self.spleeter_stem = ctk.StringVar(value="Piano")

        self._on_change = on_change
        self._build_separator(
            "demucs",
            "Use Demucs",
            "Created by Meta. High-quality six-stem separation "
            "(drums, bass, vocals, guitar, piano, other) — accurate but a bit slower.",
            self.use_demucs,
            self.demucs_stem,
            demucs_ok,
        )
        self._build_separator(
            "spleeter",
            "Use Spleeter (5 stems)",
            "Created by Deezer. Faster five-stem separation "
            "(vocals, piano, drums, bass, other) — no separate guitar track.",
            self.use_spleeter,
            self.spleeter_stem,
            spleeter_ok,
        )

    def _build_separator(
        self,
        name: str,
        title: str,
        description: str,
        enabled: ctk.BooleanVar,
        stem: ctk.StringVar,
        available: bool = True,
    ) -> None:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", pady=(2, 4))
        if not available:
            description += " (not installed — run `make install`)"
        checkbox = ctk.CTkCheckBox(
            frame,
            text=title,
            variable=enabled,
            command=lambda: self._select(name),
        )
        if not available:
            checkbox.configure(state="disabled")
        checkbox.pack(anchor="w")
        ctk.CTkLabel(frame, text=description, text_color="gray").pack(
            anchor="w", padx=28
        )
        label = ctk.CTkLabel(frame, text="Stem to extract:")
        combo = ctk.CTkComboBox(
            frame,
            variable=stem,
            values=[value.title() for value in SEPARATOR_STEMS[name]],
            state="readonly",
            width=260,
        )
        if enabled.get():
            label.pack(anchor="w", padx=28, pady=(4, 0))
            combo.pack(anchor="w", fill="x", padx=28, pady=(4, 0))

        if name == "demucs":
            self.demucs_stem_label = label
            self.demucs_stem_combo = combo
        else:
            self.spleeter_stem_label = label
            self.spleeter_stem_combo = combo

    def selection(self) -> tuple[str, str] | None:
        if self.use_demucs.get() == self.use_spleeter.get():
            return None
        if self.use_demucs.get():
            return "demucs", self.demucs_stem.get().lower()
        return "spleeter", self.spleeter_stem.get().lower()

    def _select(self, selected: str) -> None:
        if selected == "demucs" and self.use_demucs.get():
            self.use_spleeter.set(False)
        elif selected == "spleeter" and self.use_spleeter.get():
            self.use_demucs.set(False)
        self._update_controls()
        self._on_change()

    def _update_controls(self) -> None:
        if self.use_demucs.get():
            self.demucs_stem_label.pack(anchor="w", padx=28, pady=(4, 0))
            self.demucs_stem_combo.pack(
                anchor="w", fill="x", padx=28, pady=(4, 0)
            )
        else:
            self.demucs_stem_label.pack_forget()
            self.demucs_stem_combo.pack_forget()
        if self.use_spleeter.get():
            self.spleeter_stem_label.pack(anchor="w", padx=28, pady=(4, 0))
            self.spleeter_stem_combo.pack(
                anchor="w", fill="x", padx=28, pady=(4, 0)
            )
        else:
            self.spleeter_stem_label.pack_forget()
            self.spleeter_stem_combo.pack_forget()


class AMTPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_change: Callable[[], None],
        available: dict[str, bool] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        available = available or {name: True for name in AMT_MODELS}
        first_available = next(
            (name for name in AMT_MODELS if available.get(name, False)), None
        )
        self.enabled_vars = {
            name: ctk.BooleanVar(value=name == first_available)
            for name in AMT_MODELS
        }
        self.weight_vars = {name: ctk.IntVar(value=100) for name in AMT_MODELS}
        self.weight_sliders: dict[str, ctk.CTkSlider] = {}
        self.weight_labels: dict[str, ctk.CTkLabel] = {}
        self._on_change = on_change

        ctk.CTkLabel(
            self,
            text="Piano transcription models",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", pady=(2, 4))
        ctk.CTkLabel(
            self,
            text="Select one or more models and set their relative fusion weights.",
            text_color="gray",
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", pady=(0, 4))

        descriptions = {
            "basic_pitch": "Spotify. Lightweight piano transcription.",
            "magenta": "Google. Onsets & Frames for piano.",
            "bytedance": "ByteDance. High-resolution piano transcription with pedals.",
            "omnizart": "Music and Culture Technology Lab. General music transcription.",
        }
        options = ctk.CTkScrollableFrame(self, height=300, fg_color="transparent")
        options.pack(fill="x")
        for model_name, label in AMT_MODELS.items():
            is_available = bool(available.get(model_name, False))
            self._build_model_row(
                options, model_name, label, descriptions[model_name], is_available
            )

    def _build_model_row(
        self,
        parent,
        model_name: str,
        label: str,
        description: str,
        is_available: bool,
    ) -> None:
        if not is_available:
            description += (
                " (unavailable — start Docker Desktop and run `make install`)"
            )

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(4, 6))

        checkbox = ctk.CTkCheckBox(
            row,
            text=label,
            variable=self.enabled_vars[model_name],
            command=lambda name=model_name: self._on_toggle(name),
        )
        if not is_available:
            checkbox.configure(state="disabled")
        checkbox.pack(anchor="w")

        ctk.CTkLabel(
            row,
            text=description,
            text_color="gray",
            wraplength=650,
            justify="left",
        ).pack(anchor="w", padx=28, pady=(0, 4))

        weight_row = ctk.CTkFrame(row, fg_color="transparent")
        weight_row.pack(fill="x", padx=28)
        ctk.CTkLabel(weight_row, text="Weight", text_color="gray").pack(
            side="left", padx=(0, 10)
        )
        slider = ctk.CTkSlider(
            weight_row,
            from_=0,
            to=100,
            number_of_steps=100,
            variable=self.weight_vars[model_name],
            command=lambda value, name=model_name: self._on_weight(name, value),
        )
        slider.pack(side="left", fill="x", expand=True, padx=(0, 10))
        weight_label = ctk.CTkLabel(weight_row, text="100%", width=52, anchor="w")
        weight_label.pack(side="right")
        self.weight_sliders[model_name] = slider
        self.weight_labels[model_name] = weight_label

        self._update_row_state(model_name)

    def selection(self) -> dict[str, float] | None:
        selected: dict[str, float] = {}
        for model_name, variable in self.enabled_vars.items():
            if not variable.get():
                continue
            weight = self.weight_vars[model_name].get() / 100.0
            if weight > 0:
                selected[model_name] = weight
        return selected or None

    def _on_toggle(self, model_name: str) -> None:
        self._update_row_state(model_name)
        self._on_change()

    def _on_weight(self, model_name: str, value: float) -> None:
        self.weight_labels[model_name].configure(text=f"{round(value)}%")
        self._on_change()

    def _update_row_state(self, model_name: str) -> None:
        enabled = self.enabled_vars[model_name].get()
        self.weight_sliders[model_name].configure(
            state="normal" if enabled else "disabled"
        )
        self.weight_labels[model_name].configure(
            text=f"{self.weight_vars[model_name].get()}%"
        )


class PlaybackConfig:
    """Tempo/colour/loop settings shared by the MIDI and Device stages."""

    def __init__(self) -> None:
        self.bpm = IntVar(value=120)
        self.split_pitch = IntVar(value=60)
        self.prepare_ms = IntVar(value=500)
        self.left_prepare = StringVar(value="#7dd3fc")
        self.left_click = StringVar(value="#0284c7")
        self.right_prepare = StringVar(value="#fcd34d")
        self.right_click = StringVar(value="#d97706")
        self.loop_start = DoubleVar(value=0.0)
        self.loop_end = DoubleVar(value=0.0)
        self.loop_enabled = BooleanVar(value=False)

    def export_settings(self) -> ExportSettings:
        return ExportSettings(
            bpm=self.bpm.get(),
            split_pitch=self.split_pitch.get(),
            colors=LedColors(
                left_prepare=self.left_prepare.get(),
                left_click=self.left_click.get(),
                right_prepare=self.right_prepare.get(),
                right_click=self.right_click.get(),
            ),
        )

    def loop_range(self) -> tuple[float, float] | None:
        if not self.loop_enabled.get():
            return None
        start, end = self.loop_start.get(), self.loop_end.get()
        if end <= start:
            return None
        return start, end


class ColorRow(ctk.CTkFrame):
    """A labelled colour swatch that opens the system colour picker."""

    def __init__(
        self,
        master,
        label: str,
        variable: StringVar,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._variable = variable
        self._on_change = on_change

        ctk.CTkLabel(self, text=label, width=150, anchor="w").pack(
            side="left", padx=(0, 8)
        )
        self.swatch = ctk.CTkButton(
            self,
            text="",
            width=44,
            height=26,
            corner_radius=6,
            fg_color=variable.get(),
            hover_color=variable.get(),
            command=self._pick,
        )
        self.swatch.pack(side="left", padx=(0, 8))
        self.hex_label = ctk.CTkLabel(
            self, text=variable.get(), width=84, anchor="w", text_color="gray"
        )
        self.hex_label.pack(side="left")

    def _pick(self) -> None:
        result = colorchooser.askcolor(
            color=self._variable.get(), parent=self.winfo_toplevel()
        )
        if result and result[1]:
            self._variable.set(result[1])
            self._refresh()
            self._on_change()

    def _refresh(self) -> None:
        color = self._variable.get()
        self.swatch.configure(fg_color=color, hover_color=color)
        self.hex_label.configure(text=color)


class MidiPanel(ctk.CTkFrame):
    """Stage 4: preview and download the fused MIDI."""

    def __init__(
        self,
        master,
        config: PlaybackConfig,
        on_download: Callable[[], None],
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.config = config
        self._on_change = on_change
        self._notes: list[FusedNote] = []

        ctk.CTkLabel(
            self, text="MIDI download", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", pady=(2, 4))
        ctk.CTkLabel(
            self,
            text="Preview the transcribed notes, then download the MIDI file.",
            text_color="gray",
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", pady=(0, 6))

        self.view = PianoRollView(self, height=220)
        self.view.pack(fill="x", pady=(0, 4))

        self.download_btn = ctk.CTkButton(
            self,
            text="Download MIDI",
            command=on_download,
            state="disabled",
            height=36,
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.download_btn.pack(pady=(2, 0))

    def set_notes(self, notes: list[FusedNote]) -> None:
        self._notes = notes
        self.view.set_notes(notes, self.config.export_settings())
        self.download_btn.configure(state="normal" if notes else "disabled")

    def refresh(self) -> None:
        self.view.set_settings(self.config.export_settings())


class DevicePanel(ctk.CTkFrame):
    """Stage 5: select a fragment, loop it, and send events to the device."""

    def __init__(
        self,
        master,
        config: PlaybackConfig,
        on_send: Callable[[], None],
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.config = config
        self._on_change = on_change
        self._notes: list[FusedNote] = []
        self._duration = 0.0

        ctk.CTkLabel(
            self, text="Edge device", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", pady=(2, 4))
        ctk.CTkLabel(
            self,
            text="Set tempo and hand colours, drag on the piano roll to select a fragment, then send the LED events to the edge device.",
            text_color="gray",
            font=ctk.CTkFont(size=12),
            wraplength=660,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        self.view = PianoRollView(
            self, height=180, selectable=True, on_selection=self._on_selection
        )
        self.view.pack(fill="x", pady=(0, 6))

        loop_row = ctk.CTkFrame(self, fg_color="transparent")
        loop_row.pack(fill="x", pady=(0, 4))
        ctk.CTkCheckBox(
            loop_row,
            text="Loop selected fragment",
            variable=config.loop_enabled,
            command=self._on_loop_toggle,
        ).pack(side="left")
        self.loop_label = ctk.CTkLabel(loop_row, text="No fragment selected", text_color="gray")
        self.loop_label.pack(side="left", padx=(12, 0))
        ctk.CTkButton(
            loop_row,
            text="Clear",
            width=70,
            height=26,
            command=self._clear_selection,
            fg_color="transparent",
            border_width=1,
            text_color=("gray10", "gray90"),
        ).pack(side="right")

        prepare_row = ctk.CTkFrame(self, fg_color="transparent")
        prepare_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(prepare_row, text="Prepare lead (ms)", width=150, anchor="w").pack(
            side="left", padx=(0, 10)
        )
        ctk.CTkSlider(
            prepare_row,
            from_=0,
            to=2000,
            number_of_steps=40,
            variable=config.prepare_ms,
            command=self._on_prepare,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.prepare_label = ctk.CTkLabel(
            prepare_row, text=f"{config.prepare_ms.get()} ms", width=64, anchor="w"
        )
        self.prepare_label.pack(side="right")

        settings_frame = ctk.CTkFrame(self, fg_color="transparent")
        settings_frame.pack(fill="x", pady=(2, 0))

        tempo_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        tempo_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(tempo_row, text="Tempo", width=150, anchor="w").pack(
            side="left", padx=(0, 10)
        )
        ctk.CTkSlider(
            tempo_row,
            from_=30,
            to=240,
            number_of_steps=210,
            variable=config.bpm,
            command=self._on_tempo,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.tempo_label = ctk.CTkLabel(
            tempo_row, text=f"{config.bpm.get()} BPM", width=64, anchor="w"
        )
        self.tempo_label.pack(side="right")

        split_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        split_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(split_row, text="Hand split", width=150, anchor="w").pack(
            side="left", padx=(0, 10)
        )
        ctk.CTkSlider(
            split_row,
            from_=48,
            to=72,
            number_of_steps=24,
            variable=config.split_pitch,
            command=self._on_split,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.split_label = ctk.CTkLabel(
            split_row, text=midi_note_name(config.split_pitch.get()), width=64, anchor="w"
        )
        self.split_label.pack(side="right")

        ctk.CTkLabel(
            settings_frame,
            text="Hand colours (prepare / click)",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", pady=(2, 2))
        for label, var in (
            ("Left prepare colour", config.left_prepare),
            ("Left click colour", config.left_click),
            ("Right prepare colour", config.right_prepare),
            ("Right click colour", config.right_click),
        ):
            ColorRow(settings_frame, label, var, self._on_colour_change).pack(
                fill="x", pady=(0, 3)
            )

        self.summary_lbl = ctk.CTkLabel(
            self,
            text="",
            text_color="gray",
            font=ctk.CTkFont(size=11),
            wraplength=660,
            justify="left",
        )
        self.summary_lbl.pack(anchor="w", pady=(0, 6))

        self.send_btn = ctk.CTkButton(
            self,
            text="Send to device",
            command=on_send,
            state="disabled",
            height=36,
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.send_btn.pack(pady=(0, 0))

        self._bind_traces()

    def _bind_traces(self) -> None:
        for var in (
            self.config.bpm,
            self.config.split_pitch,
            self.config.left_prepare,
            self.config.left_click,
            self.config.right_prepare,
            self.config.right_click,
        ):
            var.trace_add("write", lambda *_: self.refresh())

    def _on_selection(self, selection: tuple[float, float]) -> None:
        start, end = selection
        self.config.loop_start.set(round(start, 3))
        self.config.loop_end.set(round(end, 3))
        self._update_loop_label()
        self._on_change()

    def _on_loop_toggle(self) -> None:
        self._update_loop_label()
        self._on_change()

    def _on_prepare(self, value: float) -> None:
        self.prepare_label.configure(text=f"{round(float(value))} ms")
        self._on_change()

    def _on_tempo(self, value: float) -> None:
        self.tempo_label.configure(text=f"{round(float(value))} BPM")
        self._on_change()

    def _on_split(self, value: float) -> None:
        self.split_label.configure(text=midi_note_name(int(round(float(value)))))
        self.refresh()
        self._on_change()

    def _on_colour_change(self) -> None:
        self.refresh()
        self._on_change()

    def _clear_selection(self) -> None:
        self.config.loop_start.set(0.0)
        self.config.loop_end.set(self._duration)
        self.view.set_selection(None)
        self._update_loop_label()
        self._on_change()

    def set_notes(self, notes: list[FusedNote]) -> None:
        self._notes = notes
        self._duration = notes_duration(notes)
        self.view.set_notes(notes, self.config.export_settings())
        if notes:
            self.config.loop_start.set(0.0)
            self.config.loop_end.set(round(self._duration, 3))
            self.view.set_selection((0.0, self._duration))
            self.send_btn.configure(state="normal")
        else:
            self.view.set_selection(None)
            self.send_btn.configure(state="disabled")
        self._update_loop_label()
        self._update_summary()

    def refresh(self) -> None:
        self.view.set_settings(self.config.export_settings())
        self._update_summary()

    def _update_loop_label(self) -> None:
        if self.config.loop_enabled.get():
            self.loop_label.configure(
                text=f"{self.config.loop_start.get():.2f}s - {self.config.loop_end.get():.2f}s"
            )
        else:
            self.loop_label.configure(text="Loop disabled")

    def _update_summary(self) -> None:
        settings = self.config.export_settings()
        self.summary_lbl.configure(
            text=(
                f"Tempo {settings.bpm} BPM - split {midi_note_name(settings.split_pitch)} - "
                f"left {settings.colors.left_prepare}/{settings.colors.left_click} - "
                f"right {settings.colors.right_prepare}/{settings.colors.right_click}"
            )
        )
