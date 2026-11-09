from pathlib import Path
from tkinter import StringVar
from typing import Callable, Sequence

import customtkinter as ctk

from kivipiano.separation import SEPARATOR_STEMS
from kivipiano.transcription import AMT_MODELS


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
    def __init__(self, master, on_change: Callable[[], None]) -> None:
        super().__init__(master, fg_color="transparent")
        self.use_demucs = ctk.BooleanVar(value=True)
        self.demucs_stem = ctk.StringVar(value="Piano")
        self.use_spleeter = ctk.BooleanVar(value=False)
        self.spleeter_stem = ctk.StringVar(value="Piano")

        self._on_change = on_change
        self._build_separator(
            "demucs",
            "Use Demucs",
            "Six stems, including guitar; usually slower.",
            self.use_demucs,
            self.demucs_stem,
        )
        self._build_separator(
            "spleeter",
            "Use Spleeter (5 stems)",
            "Five stems; usually faster; no separate guitar stem.",
            self.use_spleeter,
            self.spleeter_stem,
        )

    def _build_separator(
        self,
        name: str,
        title: str,
        description: str,
        enabled: ctk.BooleanVar,
        stem: ctk.StringVar,
    ) -> None:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", pady=(2, 4))
        ctk.CTkCheckBox(
            frame,
            text=title,
            variable=enabled,
            command=lambda: self._select(name),
        ).pack(anchor="w")
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
    def __init__(self, master, on_change: Callable[[], None]) -> None:
        super().__init__(master, fg_color="transparent")
        self.use_basic_pitch = ctk.BooleanVar(value=True)
        self.use_magenta = ctk.BooleanVar(value=False)
        self._on_change = on_change

        ctk.CTkLabel(
            self,
            text="Piano transcription model",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", pady=(2, 4))
        ctk.CTkCheckBox(
            self,
            text=AMT_MODELS["basic_pitch"],
            variable=self.use_basic_pitch,
            command=lambda: self._select("basic_pitch"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            self,
            text="Transcribes the separated audio and writes MIDI and note CSV.",
            text_color="gray",
        ).pack(anchor="w", padx=28, pady=(0, 3))
        ctk.CTkCheckBox(
            self,
            text=AMT_MODELS["magenta"],
            variable=self.use_magenta,
            command=lambda: self._select("magenta"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            self,
            text="Requires the optional Python 3.10 Magenta environment.",
            text_color="gray",
        ).pack(anchor="w", padx=28)

    def selection(self) -> str | None:
        if self.use_basic_pitch.get() == self.use_magenta.get():
            return None
        return "basic_pitch" if self.use_basic_pitch.get() else "magenta"

    def _select(self, selected: str) -> None:
        if selected == "basic_pitch" and self.use_basic_pitch.get():
            self.use_magenta.set(False)
        elif selected == "magenta" and self.use_magenta.get():
            self.use_basic_pitch.set(False)
        self._on_change()
