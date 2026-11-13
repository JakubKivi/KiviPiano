import os
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from tkinter import filedialog, messagebox

import customtkinter as ctk

from kivipiano.config import AppPaths
from kivipiano.fusion import FusedNote, read_fused_csv, write_fused_csv, write_fused_midi
from kivipiano.media import list_saved_audio
from kivipiano.midi_export import (
    DeviceTransport,
    LoggingTransport,
    build_device_events,
    write_tempo_midi,
)
from kivipiano.musical_context import context_available
from kivipiano.separation import demucs_available, spleeter_available
from kivipiano.services.processing import (
    AudioProcessingService,
    ModelWeight,
    ProcessingRequest,
)
from kivipiano.transcription import AMT_MODELS, amt_model_available
from kivipiano.ui.components import (
    AMTPanel,
    ContextPanel,
    DevicePanel,
    FiltersPanel,
    InputPanel,
    MidiPanel,
    PlaybackConfig,
    SeparatorPanel,
)


ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class KiviPianoApp(ctk.CTk):
    def __init__(
        self,
        paths: AppPaths | None = None,
        processing_service: AudioProcessingService | None = None,
    ) -> None:
        super().__init__()
        self.paths = paths or AppPaths.default()
        self.processing_service = processing_service or AudioProcessingService(
            self.paths
        )

        self.title("KiviPiano - Piano Transcription")
        self.geometry("760x900")
        self.minsize(680, 780)

        self.processing_results: Queue[
            tuple[bool, str, Path | None, Path | None, Path | None, tuple | None]
        ] = Queue()
        self.progress_messages: Queue[str] = Queue()
        self.processing = False
        self.output_file: Path | None = None
        self.fused_midi_path: Path | None = None
        self.fused_notes: list[FusedNote] = []
        self.raw_fused_notes: list[FusedNote] = []
        self.device_transport: DeviceTransport = LoggingTransport()

        self._build_ui()
        self.refresh_library()
        self._update_process_button()

    def _build_ui(self) -> None:
        self.main_frame = ctk.CTkFrame(self, corner_radius=15)
        self.main_frame.pack(pady=18, padx=18, fill="both", expand=True)

        ctk.CTkLabel(
            self.main_frame,
            text="KiviPiano - Piano Transcription",
            font=ctk.CTkFont(size=23, weight="bold"),
        ).pack(pady=(20, 2))
        ctk.CTkLabel(
            self.main_frame,
            text="Separate a piano stem and transcribe its notes.",
            text_color="gray",
            font=ctk.CTkFont(size=13),
        ).pack(pady=(0, 12))

        self.steps = [
            "file",
            "separator",
            "amt",
            "context",
            "filters",
            "midi",
            "device",
        ]
        self.step_labels = {
            "file": "1. File",
            "separator": "2. Separator",
            "amt": "3. AMT models",
            "context": "4. Beats & Chords",
            "filters": "5. Filters",
            "midi": "6. MIDI",
            "device": "7. Device",
        }
        self.current_step = ctk.StringVar(value=self.steps[0])

        step_bar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        step_bar.pack(fill="x", padx=20, pady=(0, 10))
        self.step_radios: dict[str, ctk.CTkRadioButton] = {}
        for value in self.steps:
            self.step_radios[value] = ctk.CTkRadioButton(
                step_bar,
                text=self.step_labels[value],
                variable=self.current_step,
                value=value,
                command=self._show_step,
            )
            self.step_radios[value].pack(side="left", padx=(0, 16))

        self.step_container = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.step_container.pack(fill="x", pady=(0, 8))

        self.input_panel = InputPanel(
            self.step_container,
            on_change=self._update_process_button,
            on_browse=self.browse_file,
            on_refresh=self.refresh_library,
        )
        model_dir = self.paths.model_dir
        self.separator_panel = SeparatorPanel(
            self.step_container,
            on_change=self._update_process_button,
            available={
                "demucs": demucs_available(model_dir),
                "spleeter": spleeter_available(model_dir),
            },
        )
        self.amt_panel = AMTPanel(
            self.step_container,
            on_change=self._update_process_button,
            available={
                model_name: amt_model_available(model_name, model_dir)
                for model_name in AMT_MODELS
            },
        )
        self.context_panel = ContextPanel(
            self.step_container,
            on_change=self._update_process_button,
            available=context_available(),
        )
        self.playback_config = PlaybackConfig()
        self.filters_panel = FiltersPanel(
            self.step_container,
            config=self.playback_config,
            on_change=self._on_filters_changed,
            on_apply=self._apply_filters,
        )
        self.midi_panel = MidiPanel(
            self.step_container,
            config=self.playback_config,
            on_download=self.download_midi,
            on_change=self._update_process_button,
        )
        self.device_panel = DevicePanel(
            self.step_container,
            config=self.playback_config,
            on_send=self.send_to_device,
            on_change=self._update_process_button,
        )
        self.step_panels = {
            "file": self.input_panel,
            "separator": self.separator_panel,
            "amt": self.amt_panel,
            "context": self.context_panel,
            "filters": self.filters_panel,
            "midi": self.midi_panel,
            "device": self.device_panel,
        }

        self.nav_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.nav_frame.pack(fill="x", padx=20, pady=(4, 10))

        self.back_btn = ctk.CTkButton(
            self.nav_frame,
            text="Back",
            command=self._previous_step,
            width=110,
            height=38,
            fg_color="transparent",
            border_width=1,
            text_color=("gray10", "gray90"),
        )
        self.next_btn = ctk.CTkButton(
            self.nav_frame,
            text="Next",
            command=self._next_step,
            width=110,
            height=38,
        )
        self.process_btn = ctk.CTkButton(
            self.nav_frame,
            text="Process",
            command=self.process_file,
            state="disabled",
            width=130,
            height=38,
            font=ctk.CTkFont(size=15, weight="bold"),
        )

        self.open_output_btn = ctk.CTkButton(
            self.main_frame,
            text="Open Output Folder",
            command=self.open_output_folder,
            state="disabled",
            height=34,
        )
        self.open_output_btn.pack(pady=(0, 10))
        self.progress = ctk.CTkProgressBar(self.main_frame, mode="indeterminate")
        self.progress.pack(fill="x", padx=25, pady=(0, 8))
        self.progress.pack_forget()
        self.status_lbl = ctk.CTkLabel(
            self.main_frame,
            text="Choose an MP3/WAV file or enter a YouTube URL.",
            text_color="gray",
            font=ctk.CTkFont(size=12),
            wraplength=680,
            justify="left",
        )
        self.status_lbl.pack(fill="x", padx=20, side="bottom", pady=(0, 15))

        self._show_step()

    def _show_step(self) -> None:
        step = self.current_step.get()
        for value, panel in self.step_panels.items():
            if value == step:
                panel.pack(fill="x", padx=20, pady=(0, 10))
            else:
                panel.pack_forget()
        self._update_step_access()
        self._update_process_button()

    def _midi_ready(self) -> bool:
        """The Filters/MIDI/Device steps unlock after processing produced a file."""
        return self.fused_midi_path is not None

    def _update_step_access(self) -> None:
        ready = self._midi_ready()
        for value in ("filters", "midi", "device"):
            radio = self.step_radios.get(value)
            if radio is not None:
                radio.configure(state="normal" if ready else "disabled")
        self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        index = self.steps.index(self.current_step.get())
        step = self.current_step.get()
        for widget in (self.back_btn, self.next_btn, self.process_btn):
            widget.pack_forget()
        if index > 0:
            self.back_btn.pack(side="left")
        if index < len(self.steps) - 1:
            # The Context -> Filters transition is gated behind processing.
            if not (step == "context" and not self._midi_ready()):
                self.next_btn.pack(side="right")
            if step in ("amt", "context"):
                self.process_btn.pack(side="right", padx=(0, 8))

    def _next_step(self) -> None:
        index = self.steps.index(self.current_step.get())
        if index < len(self.steps) - 1:
            if self.current_step.get() == "filters":
                self._apply_filters()
            self.current_step.set(self.steps[index + 1])
            self._show_step()

    def _previous_step(self) -> None:
        index = self.steps.index(self.current_step.get())
        if index > 0:
            self.current_step.set(self.steps[index - 1])
            self._show_step()

    def browse_file(self) -> None:
        current_file = self.input_panel.file_path.get()
        initial_dir = (
            os.path.dirname(current_file)
            if os.path.isfile(current_file)
            else os.getcwd()
        )
        filename = filedialog.askopenfilename(
            title="Select audio file",
            initialdir=initial_dir,
            filetypes=[
                ("Audio files (MP3, WAV)", "*.mp3 *.wav"),
                ("MP3 files", "*.mp3"),
                ("WAV files", "*.wav"),
                ("All files", "*.*"),
            ],
        )
        if filename:
            self.input_panel.file_path.set(filename)
            self.input_panel.tabs.set("Audio File")
            self.status_lbl.configure(
                text=f"Selected: {os.path.basename(filename)}",
                text_color="gray",
            )

    def refresh_library(self) -> None:
        try:
            saved_files = list_saved_audio(self.paths.library_dir)
        except OSError as exc:
            self.input_panel.set_library_unavailable()
            self.status_lbl.configure(
                text=f"Could not read the audio library: {exc}",
                text_color="red",
            )
            return
        self.input_panel.set_library_files(saved_files)

    def _update_process_button(self, *_args) -> None:
        if not hasattr(self, "process_btn") or self.processing:
            return

        ready = (
            self.separator_panel.selection() is not None
            and self.amt_panel.selection() is not None
            and not self.amt_panel.validation_errors()
            and not self.context_panel.validation_errors()
            and not self.filters_panel.validation_errors()
        )
        selected_tab = self.input_panel.selected_tab
        if selected_tab == "YouTube":
            ready = ready and bool(self.input_panel.youtube_url.get().strip())
        elif selected_tab == "Saved Files":
            selected_path = self.input_panel.library_files.get(
                self.input_panel.library_selection.get()
            )
            ready = ready and selected_path is not None and selected_path.is_file()
        else:
            source_path = Path(self.input_panel.file_path.get()).expanduser()
            ready = (
                ready
                and source_path.is_file()
                and source_path.suffix.lower() in {".mp3", ".wav"}
            )
        self.process_btn.configure(state="normal" if ready else "disabled")

    def process_file(self) -> None:
        selection = self.separator_panel.selection()
        if selection is None:
            messagebox.showwarning(
                "Select a separator",
                "Select exactly one separator: Demucs or Spleeter.",
                parent=self,
            )
            return
        separator_name, stem_name = selection
        amt_selection = self.amt_panel.selection()
        if not amt_selection:
            messagebox.showwarning(
                "Select transcription models",
                "Select at least one available AMT model.",
                parent=self,
            )
            return
        amt_errors = self.amt_panel.validation_errors()
        if amt_errors:
            messagebox.showwarning(
                "Check fusion settings", amt_errors[0], parent=self
            )
            return
        amt_models = tuple(
            ModelWeight(name=name, weight=weight)
            for name, weight in amt_selection.items()
        )

        selected_tab = self.input_panel.selected_tab
        if selected_tab == "YouTube":
            source = self.input_panel.youtube_url.get().strip()
            if not source:
                messagebox.showwarning(
                    "Missing URL", "Enter a YouTube video URL.", parent=self
                )
                return
            source_mode = "youtube"
            save_for_later = self.input_panel.save_youtube.get()
        elif selected_tab == "Saved Files":
            selected_path = self.input_panel.library_files.get(
                self.input_panel.library_selection.get()
            )
            if selected_path is None or not selected_path.is_file():
                messagebox.showwarning(
                    "No saved file selected",
                    "Select an existing file from the saved files list.",
                    parent=self,
                )
                return
            source = str(selected_path)
            source_mode = "file"
            save_for_later = False
        else:
            source = self.input_panel.file_path.get()
            source_path = Path(source).expanduser()
            if not source_path.is_file():
                messagebox.showwarning(
                    "File not found",
                    "Select an existing MP3 or WAV file.",
                    parent=self,
                )
                return
            if source_path.suffix.lower() not in {".mp3", ".wav"}:
                messagebox.showwarning(
                    "Unsupported format",
                    "Select an MP3 or WAV file.",
                    parent=self,
                )
                return
            source_mode = "file"
            save_for_later = self.input_panel.save_file.get()

        request = ProcessingRequest(
            source_mode=source_mode,
            source=source,
            save_for_later=save_for_later,
            separator=separator_name,
            stem=stem_name,
            amt_models=amt_models,
            fusion=self.amt_panel.fusion_config(),
            context=self.context_panel.context_config(),
            filters=self.filters_panel.filter_config(),
        )
        self.processing = True
        self.process_btn.configure(state="disabled")
        self.status_lbl.configure(text="Processing...", text_color="gray")
        self.progress.pack(fill="x", padx=25, pady=(0, 8))
        self.progress.start()
        try:
            Thread(
                target=self._process_audio,
                args=(request,),
                name="audio-processing",
                daemon=True,
            ).start()
        except RuntimeError as exc:
            self._finish_processing(False, f"Could not start processing: {exc}")
            return
        self.after(100, self._poll_processing_result)

    def _process_audio(self, request: ProcessingRequest) -> None:
        try:
            result = self.processing_service.process(
                request,
                on_progress=self.progress_messages.put,
            )
            self.processing_results.put(
                (
                    True,
                    result.message,
                    result.selected_audio,
                    result.output_path,
                    result.midi_path,
                    result.raw_notes,
                )
            )
        except Exception as exc:
            self.processing_results.put((False, str(exc), None, None, None, None))

    def _poll_processing_result(self) -> None:
        self._drain_progress_messages()
        try:
            result = self.processing_results.get_nowait()
        except Empty:
            self.after(100, self._poll_processing_result)
            return
        self._finish_processing(*result)

    def _drain_progress_messages(self) -> None:
        while True:
            try:
                message = self.progress_messages.get_nowait()
            except Empty:
                return
            self.status_lbl.configure(text=message, text_color="gray")

    def _finish_processing(
        self,
        succeeded: bool,
        message: str,
        selected_audio: Path | None = None,
        output_file: Path | None = None,
        midi_path: Path | None = None,
        raw_notes: tuple[FusedNote, ...] | None = None,
    ) -> None:
        self.progress.stop()
        self.progress.pack_forget()
        self.processing = False
        self.status_lbl.configure(
            text=message,
            text_color="green" if succeeded else "red",
        )
        if not succeeded:
            messagebox.showerror("Audio processing failed", message, parent=self)
            self.output_file = None
            self.fused_midi_path = None
            self.open_output_btn.configure(state="disabled")
        else:
            self.output_file = output_file
            self.fused_midi_path = midi_path
            self.open_output_btn.configure(state="normal")
            self.raw_fused_notes = list(raw_notes or [])
            self.filters_panel.set_raw_notes(self.raw_fused_notes)
            if selected_audio:
                self.input_panel.file_path.set(str(selected_audio))
                self.input_panel.tabs.set("Audio File")
                self.refresh_library()
            self._load_fused_notes(output_file)
        self._update_process_button()
        self._update_step_access()
        if succeeded:
            self.current_step.set("filters")
            self._show_step()

    def open_output_folder(self) -> None:
        if self.output_file is None:
            return
        output_folder = self.output_file.parent
        try:
            os.startfile(str(output_folder))
        except OSError as exc:
            messagebox.showerror(
                "Could not open output folder",
                f"{exc}\n\nOutput folder:\n{output_folder}",
                parent=self,
            )

    def _load_fused_notes(self, fused_csv: Path | None) -> None:
        if fused_csv is None:
            self.fused_notes = []
            self.midi_panel.set_notes([])
            self.device_panel.set_notes([])
            return
        try:
            notes = read_fused_csv(fused_csv)
        except Exception as exc:
            notes = []
            self.status_lbl.configure(
                text=f"Done, but the fused notes could not be previewed: {exc}",
                text_color="red",
            )
        self.fused_notes = notes
        self.midi_panel.set_notes(notes)
        self.device_panel.set_notes(notes)

    def _on_filters_changed(self) -> None:
        """Keep the MIDI/Device previews in sync with the current filters."""
        notes = self.filters_panel.filtered_notes()
        self.fused_notes = notes
        self.midi_panel.set_notes(notes)
        self.device_panel.set_notes(notes)

    def _apply_filters(self) -> None:
        if self.output_file is None or self.fused_midi_path is None:
            return
        notes = self.filters_panel.filtered_notes()
        try:
            write_fused_csv(notes, self.output_file)
            write_fused_midi(notes, self.fused_midi_path)
        except Exception as exc:
            messagebox.showerror("Could not apply filters", str(exc), parent=self)
            return
        self.fused_notes = notes
        self.midi_panel.set_notes(notes)
        self.device_panel.set_notes(notes)
        self.status_lbl.configure(
            text=f"Applied filters: {len(notes)} notes kept.",
            text_color="green",
        )

    def download_midi(self) -> None:
        if not self.fused_notes or self.fused_midi_path is None:
            messagebox.showwarning(
                "No MIDI yet",
                "Process audio first to produce a MIDI file.",
                parent=self,
            )
            return
        target = filedialog.asksaveasfilename(
            title="Save MIDI",
            defaultextension=".mid",
            initialfile=self.fused_midi_path.name,
            filetypes=[("MIDI files", "*.mid"), ("All files", "*.*")],
        )
        if not target:
            return
        try:
            write_tempo_midi(
                self.fused_notes,
                Path(target),
                self.playback_config.export_settings(),
            )
        except Exception as exc:
            messagebox.showerror("Could not save MIDI", str(exc), parent=self)
            return
        self.status_lbl.configure(text=f"Saved MIDI: {target}", text_color="green")

    def send_to_device(self) -> None:
        if not self.fused_notes:
            messagebox.showwarning(
                "No MIDI yet",
                "Process audio first to produce a MIDI file.",
                parent=self,
            )
            return
        settings = self.playback_config.export_settings()
        loop = self.playback_config.loop_range()
        events = build_device_events(
            self.fused_notes,
            settings,
            prepare_ms=self.playback_config.prepare_ms.get(),
            loop=loop,
        )
        if not events:
            messagebox.showwarning(
                "Empty selection",
                "No notes start inside the selected fragment.",
                parent=self,
            )
            return
        try:
            self.device_transport.send(events)
        except Exception as exc:
            messagebox.showerror("Could not send to device", str(exc), parent=self)
            return
        scope = (
            f"fragment {loop[0]:.2f}s-{loop[1]:.2f}s"
            if loop
            else "whole piece"
        )
        self.status_lbl.configure(
            text=f"Sent {len(events)} events to the edge device "
            f"({scope}, preview transport).",
            text_color="green",
        )
