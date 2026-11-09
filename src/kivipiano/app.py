import os
import tempfile
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from tkinter import filedialog, messagebox

import customtkinter as ctk

from kivipiano.config import AppPaths
from kivipiano.media import list_saved_audio
from kivipiano.separation import demucs_available, spleeter_available
from kivipiano.services.processing import AudioProcessingService, ProcessingRequest
from kivipiano.transcription import AMT_MODELS, basic_pitch_available, magenta_available
from kivipiano.ui.components import AMTPanel, InputPanel, SeparatorPanel


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
        self.geometry("760x850")
        self.minsize(680, 760)

        self.processing_results: Queue[
            tuple[bool, str, Path | None, Path | None]
        ] = Queue()
        self.processing = False
        self.output_file: Path | None = None

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

        self.input_panel = InputPanel(
            self.main_frame,
            on_change=self._update_process_button,
            on_browse=self.browse_file,
            on_refresh=self.refresh_library,
        )
        self.input_panel.pack(fill="x", padx=20, pady=(0, 12))
        model_dir = self.paths.model_dir
        self.separator_panel = SeparatorPanel(
            self.main_frame,
            on_change=self._update_process_button,
            available={
                "demucs": demucs_available(model_dir),
                "spleeter": spleeter_available(model_dir),
            },
        )
        self.separator_panel.pack(fill="x", padx=32, pady=(2, 4))
        self.amt_panel = AMTPanel(
            self.main_frame,
            on_change=self._update_process_button,
            available={
                "basic_pitch": basic_pitch_available(),
                "magenta": magenta_available(model_dir),
            },
        )
        self.amt_panel.pack(fill="x", padx=32, pady=(4, 8))

        self.process_btn = ctk.CTkButton(
            self.main_frame,
            text="Process",
            command=self.process_file,
            state="disabled",
            height=42,
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        self.process_btn.pack(pady=(4, 12))
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
        amt_model = self.amt_panel.selection()
        if amt_model is None:
            messagebox.showwarning(
                "Select a transcription model",
                "Select exactly one AMT model: Basic Pitch or Google Magenta.",
                parent=self,
            )
            return

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
            amt_model=amt_model,
        )
        self.processing = True
        self.process_btn.configure(state="disabled")
        self.status_lbl.configure(
            text=(
                f"Checking URL, downloading audio, extracting the {stem_name} "
                f"stem with {separator_name.title()}, then transcribing with "
                f"{AMT_MODELS[amt_model]}..."
                if source_mode == "youtube"
                else f"Extracting the {stem_name} stem with "
                f"{separator_name.title()}, then transcribing with "
                f"{AMT_MODELS[amt_model]}..."
            ),
            text_color="gray",
        )
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
            result = self.processing_service.process(request)
            self.processing_results.put(
                (True, result.message, result.selected_audio, result.output_path)
            )
        except Exception as exc:
            self.processing_results.put((False, str(exc), None, None))

    def _poll_processing_result(self) -> None:
        try:
            result = self.processing_results.get_nowait()
        except Empty:
            self.after(100, self._poll_processing_result)
            return
        self._finish_processing(*result)

    def _finish_processing(
        self,
        succeeded: bool,
        message: str,
        selected_audio: Path | None = None,
        output_file: Path | None = None,
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
            self.open_output_btn.configure(state="disabled")
        else:
            self.output_file = output_file
            self.open_output_btn.configure(state="normal")
            if selected_audio:
                self.input_panel.file_path.set(str(selected_audio))
                self.input_panel.tabs.set("Audio File")
                self.refresh_library()
        self._update_process_button()

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
