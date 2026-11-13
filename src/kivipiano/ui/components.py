from pathlib import Path
from tkinter import BooleanVar, DoubleVar, IntVar, StringVar, colorchooser
from typing import Callable, Sequence

import customtkinter as ctk

from kivipiano.filters import FilterConfig, apply_filters
from kivipiano.fusion import FUSION_STRATEGIES, FusedNote, FusionConfig
from kivipiano.midi_export import (
    ExportSettings,
    LedColors,
    midi_note_name,
    notes_duration,
)
from kivipiano.musical_context import ContextConfig
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


class FusionSettingsPanel(ctk.CTkFrame):
    """Editable fusion parameters shared by the processing step."""

    def __init__(self, master, on_change: Callable[[], None]) -> None:
        super().__init__(master, fg_color="transparent")
        self._on_change = on_change
        self.strategy = StringVar(value="weighted_vote")
        self.overlap_percent = IntVar(value=25)
        self.confidence_percent = IntVar(value=0)

        ctk.CTkLabel(
            self,
            text="Fusion settings",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", pady=(8, 4))

        strategy_row = ctk.CTkFrame(self, fg_color="transparent")
        strategy_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(strategy_row, text="Strategy", text_color="gray").pack(
            side="left", padx=(0, 10)
        )
        self.strategy_combo = ctk.CTkComboBox(
            strategy_row,
            variable=self.strategy,
            values=list(FUSION_STRATEGIES),
            state="readonly",
            command=lambda _value: self._on_change(),
        )
        self.strategy_combo.pack(side="left")

        self.overlap_label = ctk.CTkLabel(self, text="0.25", width=64, anchor="e")
        self._build_fraction_slider(
            "Overlap threshold",
            "Minimum time overlap (as a fraction of the shorter note) for two "
            "notes to be treated as the same event.",
            self.overlap_percent,
            self.overlap_label,
        )
        self.confidence_label = ctk.CTkLabel(self, text="0.00", width=64, anchor="e")
        self._build_fraction_slider(
            "Minimum confidence",
            "Fused notes whose confidence is below this value are dropped.",
            self.confidence_percent,
            self.confidence_label,
        )

        self._refresh_labels()

    def _build_fraction_slider(
        self,
        title: str,
        description: str,
        variable: ctk.IntVar,
        value_label: ctk.CTkLabel,
    ) -> None:
        ctk.CTkLabel(self, text=title, text_color="gray").pack(
            anchor="w", padx=28, pady=(6, 0)
        )
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=28)
        slider = ctk.CTkSlider(
            row,
            from_=0,
            to=100,
            number_of_steps=100,
            variable=variable,
            command=lambda _value: self._refresh_labels(),
        )
        slider.pack(side="left", fill="x", expand=True, padx=(0, 10))
        value_label.pack(side="right")
        ctk.CTkLabel(
            self,
            text=description,
            text_color="gray",
            wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=28, pady=(0, 4))

    def _refresh_labels(self) -> None:
        self.overlap_label.configure(text=f"{self.overlap_percent.get() / 100:.2f}")
        self.confidence_label.configure(
            text=f"{self.confidence_percent.get() / 100:.2f}"
        )
        self._on_change()

    def config(self) -> FusionConfig:
        return FusionConfig(
            strategy=self.strategy.get(),
            overlap_threshold=self.overlap_percent.get() / 100.0,
            min_confidence=self.confidence_percent.get() / 100.0,
        )

    def validation_errors(self) -> list[str]:
        try:
            self.config().validate()
        except ValueError as exc:
            return [str(exc)]
        return []


class FilterSettingsPanel(ctk.CTkFrame):
    """Editable note filters applied to the fused notes after fusion."""

    def __init__(self, master, on_change: Callable[[], None]) -> None:
        super().__init__(master, fg_color="transparent")
        self._on_change = on_change

        self.duration_enabled = ctk.BooleanVar(value=True)
        self.velocity_enabled = ctk.BooleanVar(value=True)
        self.pitch_enabled = ctk.BooleanVar(value=True)
        self.merge_enabled = ctk.BooleanVar(value=True)
        self.polyphony_enabled = ctk.BooleanVar(value=True)
        self.overtone_enabled = ctk.BooleanVar(value=True)

        self.min_duration_ms = ctk.IntVar(value=50)
        self.velocity_percent = ctk.IntVar(value=20)
        self.min_pitch = ctk.IntVar(value=28)
        self.max_pitch = ctk.IntVar(value=96)
        self.merge_gap_ms = ctk.IntVar(value=40)
        self.polyphony_max = ctk.IntVar(value=5)
        self.overtone_ratio_percent = ctk.IntVar(value=50)

        ctk.CTkLabel(
            self,
            text="Note filters",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", pady=(8, 4))
        ctk.CTkLabel(
            self,
            text="Cleanup applied to the fused notes. Toggle a filter to "
            "enable or disable it.",
            text_color="gray",
            font=ctk.CTkFont(size=12),
            wraplength=660,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))

        self._add_filter(
            "Duration gate",
            self.duration_enabled,
            "Drop notes shorter than the threshold (percussion/sibilant noise).",
            self.min_duration_ms,
            10,
            200,
            " ms",
        )
        self._add_filter(
            "Velocity gate",
            self.velocity_enabled,
            "Drop notes below this velocity percentile of the piece.",
            self.velocity_percent,
            0,
            100,
            "%",
        )
        self._add_pitch_filter()
        self._add_filter(
            "Note merging",
            self.merge_enabled,
            "Merge same-pitch notes separated by a gap smaller than the threshold.",
            self.merge_gap_ms,
            5,
            120,
            " ms",
        )
        self._add_filter(
            "Polyphony limit",
            self.polyphony_enabled,
            "Keep only this many of the loudest notes in each 50 ms window.",
            self.polyphony_max,
            1,
            12,
            "",
        )
        self._add_filter(
            "Overtone suppression",
            self.overtone_enabled,
            "Drop a quiet note 12/19 semitones above a louder simultaneous note.",
            self.overtone_ratio_percent,
            0,
            100,
            "%",
        )

    def _add_filter(
        self,
        title: str,
        enabled_var: ctk.BooleanVar,
        description: str,
        param_var: ctk.IntVar,
        low: int,
        high: int,
        unit: str,
    ) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", pady=(6, 0))
        ctk.CTkCheckBox(
            header, text=title, variable=enabled_var, command=self._on_change
        ).pack(side="left")
        value_label = ctk.CTkLabel(
            header, text=f"{param_var.get()}{unit}", width=72, anchor="e"
        )
        value_label.pack(side="right")

        slider_row = ctk.CTkFrame(self, fg_color="transparent")
        slider_row.pack(fill="x", padx=28)
        ctk.CTkSlider(
            slider_row,
            from_=low,
            to=high,
            number_of_steps=high - low,
            variable=param_var,
            command=lambda _value, v=param_var, l=value_label, u=unit: (
                self._refresh_label(v, l, u)
            ),
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkLabel(
            self,
            text=description,
            text_color="gray",
            wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=28, pady=(0, 2))

    def _refresh_label(
        self, param_var: ctk.IntVar, label: ctk.CTkLabel, unit: str
    ) -> None:
        label.configure(text=f"{param_var.get()}{unit}")
        self._on_change()

    def _add_pitch_filter(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", pady=(6, 0))
        ctk.CTkCheckBox(
            header,
            text="Pitch band-pass",
            variable=self.pitch_enabled,
            command=self._on_change,
        ).pack(side="left")
        self.pitch_range_label = ctk.CTkLabel(
            header,
            text=f"{self.min_pitch.get()}-{self.max_pitch.get()}",
            width=96,
            anchor="e",
        )
        self.pitch_range_label.pack(side="right")

        self._pitch_slider("Lowest pitch", self.min_pitch, self._on_min_pitch)
        self._pitch_slider("Highest pitch", self.max_pitch, self._on_max_pitch)

        ctk.CTkLabel(
            self,
            text="Keep only MIDI pitches inside this range (drops cymbal bleed "
            "and bass rumble).",
            text_color="gray",
            wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=28, pady=(0, 2))

    def _pitch_slider(
        self, title: str, param_var: ctk.IntVar, command: Callable
    ) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=28)
        ctk.CTkLabel(row, text=title, text_color="gray", width=96, anchor="w").pack(
            side="left", padx=(0, 10)
        )
        ctk.CTkSlider(
            row,
            from_=20,
            to=108,
            number_of_steps=88,
            variable=param_var,
            command=command,
        ).pack(side="left", fill="x", expand=True)

    def _on_min_pitch(self, _value: str) -> None:
        if self.min_pitch.get() > self.max_pitch.get():
            self.max_pitch.set(self.min_pitch.get())
        self._refresh_pitch_range()

    def _on_max_pitch(self, _value: str) -> None:
        if self.max_pitch.get() < self.min_pitch.get():
            self.min_pitch.set(self.max_pitch.get())
        self._refresh_pitch_range()

    def _refresh_pitch_range(self) -> None:
        self.pitch_range_label.configure(
            text=f"{self.min_pitch.get()}-{self.max_pitch.get()}"
        )
        self._on_change()

    def config(self) -> FilterConfig:
        return FilterConfig(
            duration_gate=self.duration_enabled.get(),
            min_duration=self.min_duration_ms.get() / 1000.0,
            velocity_gate=self.velocity_enabled.get(),
            velocity_percentile=float(self.velocity_percent.get()),
            pitch_band_pass=self.pitch_enabled.get(),
            min_pitch=self.min_pitch.get(),
            max_pitch=self.max_pitch.get(),
            merge_notes=self.merge_enabled.get(),
            merge_gap=self.merge_gap_ms.get() / 1000.0,
            polyphony_limit=self.polyphony_enabled.get(),
            polyphony_window=0.05,
            polyphony_max=self.polyphony_max.get(),
            overtone_suppression=self.overtone_enabled.get(),
            overtone_ratio=self.overtone_ratio_percent.get() / 100.0,
        )

    def validation_errors(self) -> list[str]:
        try:
            self.config().validate()
        except ValueError as exc:
            return [str(exc)]
        return []


class AMTPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_change: Callable[[], None],
        available: dict[str, bool] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._model_names = list(AMT_MODELS)
        available = available or {name: True for name in AMT_MODELS}
        first_available = next(
            (name for name in self._model_names if available.get(name, False)), None
        )
        self.enabled_vars = {
            name: ctk.BooleanVar(value=name == first_available)
            for name in self._model_names
        }
        self.weight_vars = {
            name: ctk.IntVar(value=100 if name == first_available else 0)
            for name in self._model_names
        }
        self.locked_vars = {
            name: ctk.BooleanVar(value=False) for name in self._model_names
        }
        self.weight_sliders: dict[str, ctk.CTkSlider] = {}
        self.weight_labels: dict[str, ctk.CTkLabel] = {}
        self.lock_checks: dict[str, ctk.CTkCheckBox] = {}
        self._on_change = on_change
        self._updating = False

        ctk.CTkLabel(
            self,
            text="Piano transcription models",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", pady=(2, 4))
        ctk.CTkLabel(
            self,
            text=(
                "Weights are normalized to 100% while you drag them: raising one "
                "model lowers the others. Lock a model to keep its weight fixed."
            ),
            text_color="gray",
            font=ctk.CTkFont(size=12),
            wraplength=660,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))

        descriptions = {
            "basic_pitch": "Spotify. Lightweight piano transcription.",
            "magenta": "Google. Onsets & Frames for piano.",
            "bytedance": "ByteDance. High-resolution piano transcription with pedals.",
            "omnizart": "Music and Culture Technology Lab. General music transcription.",
        }
        options = ctk.CTkScrollableFrame(self, height=280, fg_color="transparent")
        options.pack(fill="x")
        for model_name, label in AMT_MODELS.items():
            is_available = bool(available.get(model_name, False))
            self._build_model_row(
                options, model_name, label, descriptions[model_name], is_available
            )

        self.total_label = ctk.CTkLabel(
            self, text="", anchor="w", font=ctk.CTkFont(size=12, weight="bold")
        )
        self.total_label.pack(anchor="w", pady=(6, 2))

        self.fusion_settings = FusionSettingsPanel(self, on_change=self._on_change)
        self.fusion_settings.pack(fill="x", pady=(2, 4))

        self._refresh_all_labels()

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

        header = ctk.CTkFrame(row, fg_color="transparent")
        header.pack(fill="x")
        checkbox = ctk.CTkCheckBox(
            header,
            text=label,
            variable=self.enabled_vars[model_name],
            command=lambda name=model_name: self._on_toggle(name),
        )
        if not is_available:
            checkbox.configure(state="disabled")
        checkbox.pack(side="left")
        lock = ctk.CTkCheckBox(
            header,
            text="Lock",
            variable=self.locked_vars[model_name],
            command=lambda name=model_name: self._on_lock(name),
        )
        lock.pack(side="right")
        self.lock_checks[model_name] = lock

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
        weight_label = ctk.CTkLabel(weight_row, text="0%", width=52, anchor="w")
        weight_label.pack(side="right")
        self.weight_sliders[model_name] = slider
        self.weight_labels[model_name] = weight_label

        self._update_row_state(model_name)

    def selection(self) -> dict[str, float] | None:
        """Return the selected models' normalized weights (they sum to ``1``)."""
        selected: dict[str, float] = {}
        for model_name in self._model_names:
            if not self.enabled_vars[model_name].get():
                continue
            weight = self.weight_vars[model_name].get()
            if weight > 0:
                selected[model_name] = weight / 100.0
        return selected or None

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        enabled = [
            name for name in self._model_names if self.enabled_vars[name].get()
        ]
        if not enabled:
            errors.append("Select at least one transcription model.")
        else:
            total = sum(self.weight_vars[name].get() for name in enabled)
            if total != 100:
                errors.append(
                    f"Model weights must add up to 100% (currently {total}%)."
                )
            if not any(self.weight_vars[name].get() > 0 for name in enabled):
                errors.append("At least one model needs a positive weight.")
        errors.extend(self.fusion_settings.validation_errors())
        return errors

    def fusion_config(self) -> FusionConfig:
        return self.fusion_settings.config()

    def _on_toggle(self, model_name: str) -> None:
        if not self.enabled_vars[model_name].get():
            # Return the freed weight to the remaining enabled models so the
            # total stays at 100%.
            freed = self.weight_vars[model_name].get()
            self.weight_vars[model_name].set(0)
            remaining = [
                name
                for name in self._model_names
                if name != model_name and self.enabled_vars[name].get()
            ]
            unlocked = [name for name in remaining if not self.locked_vars[name].get()]
            recipients = unlocked or remaining
            if recipients and freed > 0:
                self._add_weight(recipients, freed)
        self._update_row_state(model_name)
        self._refresh_all_labels()
        self._on_change()

    def _on_lock(self, model_name: str) -> None:
        self._update_row_state(model_name)
        self._on_change()

    def _on_weight(self, model_name: str, value: float) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            self._redistribute(model_name, int(round(value)))
        finally:
            self._updating = False
        self._refresh_all_labels()
        self._on_change()

    def _redistribute(self, changed: str, target: int) -> None:
        """Move ``changed`` to ``target`` and rebalance the unlocked models.

        Locked models keep their weights; the unlocked remainder is split
        proportionally to the models' current weights (equally when they are all
        zero) so the enabled weights always add up to exactly 100.
        """
        enabled = [name for name in self._model_names if self.enabled_vars[name].get()]
        if changed not in enabled or self.locked_vars[changed].get():
            return
        locked_sum = sum(
            self.weight_vars[name].get()
            for name in enabled
            if self.locked_vars[name].get()
        )
        upper = max(0, 100 - locked_sum)
        target = max(0, min(target, upper))
        free = [
            name
            for name in enabled
            if name != changed and not self.locked_vars[name].get()
        ]
        if free:
            self.weight_vars[changed].set(target)
            remaining = 100 - locked_sum - target
            current = [self.weight_vars[name].get() for name in free]
            for name, value in zip(free, self._distribute(remaining, current)):
                self.weight_vars[name].set(value)
        else:
            self.weight_vars[changed].set(upper)

    def _add_weight(self, models: list[str], amount: int) -> None:
        current = [self.weight_vars[name].get() for name in models]
        additions = self._distribute(amount, current)
        for name, addition in zip(models, additions):
            self.weight_vars[name].set(self.weight_vars[name].get() + addition)

    @staticmethod
    def _distribute(total: int, weights: list[int]) -> list[int]:
        """Split ``total`` across ``weights`` (largest remainder), summing to it."""
        count = len(weights)
        if count == 0:
            return []
        total = max(0, total)
        weight_sum = sum(weights)
        if weight_sum <= 0:
            base, remainder = divmod(total, count)
            return [base + (1 if index < remainder else 0) for index in range(count)]
        raw = [total * weight / weight_sum for weight in weights]
        floors = [int(value) for value in raw]
        remainder = total - sum(floors)
        order = sorted(
            range(count), key=lambda index: raw[index] - floors[index], reverse=True
        )
        result = floors[:]
        for index in range(remainder):
            result[order[index]] += 1
        return result

    def _refresh_all_labels(self) -> None:
        enabled_total = 0
        for name in self._model_names:
            weight = self.weight_vars[name].get()
            self.weight_labels[name].configure(text=f"{weight}%")
            if self.enabled_vars[name].get():
                enabled_total += weight
        self.total_label.configure(
            text=f"Total: {enabled_total}%",
            text_color="green" if enabled_total == 100 else "red",
        )

    def _update_row_state(self, model_name: str) -> None:
        enabled = self.enabled_vars[model_name].get()
        locked = self.locked_vars[model_name].get()
        self.weight_sliders[model_name].configure(
            state="normal" if (enabled and not locked) else "disabled"
        )
        self.lock_checks[model_name].configure(
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


class ContextPanel(ctk.CTkFrame):
    """Stage 4: refine the fused notes with beat tracking and chord recognition.

    The analysis runs between the AMT models and the note filters; this panel
    only exposes the refinement settings and whether the Madmom image is
    installed.
    """

    def __init__(
        self,
        master,
        on_change: Callable[[], None],
        available: bool = True,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._on_change = on_change

        self.enabled = ctk.BooleanVar(value=False)
        self.beat_snap = ctk.BooleanVar(value=True)
        self.snap_tolerance_ms = ctk.IntVar(value=50)
        self.chord_filter = ctk.BooleanVar(value=True)
        self.off_beat_tolerance_ms = ctk.IntVar(value=50)

        ctk.CTkLabel(
            self,
            text="Beat & chord refinement",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", pady=(2, 4))

        description = (
            "Runs after the AMT models and before the note filters. Madmom "
            "detects the beat grid and the chord progression of the piano "
            "stem, then notes are snapped onto the beat and off-beat notes "
            "outside the current chord are dropped as false positives."
        )
        if not available:
            description += " (not installed — run `make install`)"
        ctk.CTkLabel(
            self,
            text=description,
            text_color="gray",
            font=ctk.CTkFont(size=12),
            wraplength=660,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))

        enable_row = ctk.CTkFrame(self, fg_color="transparent")
        enable_row.pack(fill="x", pady=(2, 0))
        enable_check = ctk.CTkCheckBox(
            enable_row,
            text="Enable beat & chord refinement",
            variable=self.enabled,
            command=self._on_change,
        )
        if not available:
            enable_check.configure(state="disabled")
        enable_check.pack(anchor="w")

        self._add_toggle_and_slider(
            "Beat snapping",
            self.beat_snap,
            self.snap_tolerance_ms,
            10,
            150,
            " ms",
            "Snap a note's onset onto the nearest beat when it is within this "
            "distance (fixes slight shifts when chords are struck).",
        )
        self._add_toggle_and_slider(
            "Chord false-positive filter",
            self.chord_filter,
            self.off_beat_tolerance_ms,
            10,
            150,
            " ms",
            "Drop a note that is farther than this from a beat and not part of "
            "the chord sounding at that moment.",
        )

    def _add_toggle_and_slider(
        self,
        title: str,
        enabled_var: ctk.BooleanVar,
        param_var: ctk.IntVar,
        low: int,
        high: int,
        unit: str,
        description: str,
    ) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", pady=(6, 0))
        ctk.CTkCheckBox(
            header, text=title, variable=enabled_var, command=self._on_change
        ).pack(side="left")
        value_label = ctk.CTkLabel(
            header, text=f"{param_var.get()}{unit}", width=72, anchor="e"
        )
        value_label.pack(side="right")

        slider_row = ctk.CTkFrame(self, fg_color="transparent")
        slider_row.pack(fill="x", padx=28)
        ctk.CTkSlider(
            slider_row,
            from_=low,
            to=high,
            number_of_steps=high - low,
            variable=param_var,
            command=lambda _value, v=param_var, l=value_label, u=unit: (
                self._refresh_label(v, l, u)
            ),
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkLabel(
            self,
            text=description,
            text_color="gray",
            wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=28, pady=(0, 2))

    def _refresh_label(
        self, param_var: ctk.IntVar, label: ctk.CTkLabel, unit: str
    ) -> None:
        label.configure(text=f"{param_var.get()}{unit}")
        self._on_change()

    def context_config(self) -> ContextConfig:
        return ContextConfig(
            enabled=self.enabled.get(),
            beat_snap=self.beat_snap.get(),
            snap_tolerance=self.snap_tolerance_ms.get() / 1000.0,
            chord_filter=self.chord_filter.get(),
            off_beat_tolerance=self.off_beat_tolerance_ms.get() / 1000.0,
        )

    def validation_errors(self) -> list[str]:
        try:
            self.context_config().validate()
        except ValueError as exc:
            return [str(exc)]
        return []


class FiltersPanel(ctk.CTkFrame):
    """Stage 4: tune the note filters and preview their effect live."""

    def __init__(
        self,
        master,
        config: PlaybackConfig,
        on_change: Callable[[], None],
        on_apply: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.config = config
        self._on_change = on_change
        self._raw_notes: list[FusedNote] = []

        self.settings = FilterSettingsPanel(self, on_change=self._on_settings_changed)
        self.settings.pack(fill="x", pady=(2, 4))

        self.stats_lbl = ctk.CTkLabel(
            self, text="No fused notes yet.", text_color="gray"
        )
        self.stats_lbl.pack(anchor="w", pady=(2, 4))

        self.view = PianoRollView(self, height=200)
        self.view.pack(fill="x", pady=(0, 4))

        self.apply_btn = ctk.CTkButton(
            self,
            text="Apply filters to MIDI",
            command=on_apply,
            state="disabled",
            height=36,
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.apply_btn.pack(pady=(2, 0))

    def set_raw_notes(self, notes: Sequence[FusedNote]) -> None:
        """Store the unfiltered fused notes and refresh the preview."""
        self._raw_notes = list(notes)
        self.apply_btn.configure(state="normal" if notes else "disabled")
        self._refresh()

    def filter_config(self) -> FilterConfig:
        return self.settings.config()

    def filtered_notes(self) -> list[FusedNote]:
        return apply_filters(self._raw_notes, self.filter_config())

    def validation_errors(self) -> list[str]:
        return self.settings.validation_errors()

    def _on_settings_changed(self) -> None:
        self._refresh()
        self._on_change()

    def _refresh(self) -> None:
        notes = self.filtered_notes()
        self.view.set_notes(notes, self.config.export_settings())
        if not self._raw_notes:
            text = "No fused notes yet."
        else:
            removed = len(self._raw_notes) - len(notes)
            if removed:
                text = (
                    f"{len(self._raw_notes)} fused notes -> {len(notes)} kept "
                    f"({removed} removed)"
                )
            else:
                text = f"{len(self._raw_notes)} fused notes (none removed)"
        self.stats_lbl.configure(text=text)


class MidiPanel(ctk.CTkFrame):
    """Stage 5: preview and download the fused MIDI."""

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
    """Stage 6: select a fragment, loop it, and send events to the device."""

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
