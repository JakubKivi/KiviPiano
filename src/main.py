import customtkinter as ctk
from tkinter import filedialog
import os

# Set modern appearance
ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

class KiviPianoApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Kivi Piano: Audio to LED Pipeline")
        self.geometry("600x350")
        self.resizable(False, False)
        
        self.file_path = ctk.StringVar()
        
        self.setup_ui()
        
    def setup_ui(self):
        # Main container
        self.main_frame = ctk.CTkFrame(self, corner_radius=15)
        self.main_frame.pack(pady=20, padx=20, fill="both", expand=True)
        
        # Title
        self.title_lbl = ctk.CTkLabel(self.main_frame, text="Kivi Piano: Audio to LED Pipeline", font=ctk.CTkFont(size=20, weight="bold"))
        self.title_lbl.pack(pady=(20, 15))
        
        # File selection frame
        self.file_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.file_frame.pack(fill="x", padx=20, pady=10)
        
        self.file_entry = ctk.CTkEntry(self.file_frame, textvariable=self.file_path, state="readonly", placeholder_text="No file selected...")
        self.file_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.browse_btn = ctk.CTkButton(self.file_frame, text="Browse", command=self.browse_file, width=100)
        self.browse_btn.pack(side="right")
        
        # Options frame
        self.options_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.options_frame.pack(fill="x", padx=20, pady=10)
        
        # --- Sekcja Separacji ---
        self.sep_lbl = ctk.CTkLabel(self.options_frame, text="1. Separation Models:")
        self.sep_lbl.pack(anchor="w", pady=(0, 5))

        self.use_demucs_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.options_frame, text="Meta Demucs (High Quality)", variable=self.use_demucs_var).pack(anchor="w", pady=2)

        self.use_spleeter_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.options_frame, text="Spleeter (Fast)", variable=self.use_spleeter_var).pack(anchor="w", pady=(0, 10))

        # --- Sekcja Transkrypcji ---
        self.amt_lbl = ctk.CTkLabel(self.options_frame, text="2. Transcription Models (Ensemble):")
        self.amt_lbl.pack(anchor="w", pady=(0, 5))

        self.use_basic_pitch_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.options_frame, text="Spotify Basic Pitch", variable=self.use_basic_pitch_var).pack(anchor="w", pady=2)

        self.use_magenta_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.options_frame, text="Google Magenta (Onsets & Frames)", variable=self.use_magenta_var).pack(anchor="w", pady=2)

        self.use_omnizart_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.options_frame, text="Omnizart", variable=self.use_omnizart_var).pack(anchor="w", pady=2)
        
        # Action button
        self.process_btn = ctk.CTkButton(self.main_frame, text="Process Audio", command=self.process_file, state="disabled", height=40)
        self.process_btn.pack(pady=(20, 10))
        
        # Status bar / Progress
        self.status_lbl = ctk.CTkLabel(self.main_frame, text="Ready", text_color="gray", font=ctk.CTkFont(size=12))
        self.status_lbl.pack(side="bottom", pady=(0, 15))

    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[("Audio Files", "*.mp3 *.wav"), ("All Files", "*.*")]
        )
        if filename:
            self.file_path.set(filename)
            self.process_btn.configure(state="normal")
            self.status_lbl.configure(text=f"Selected: {os.path.basename(filename)}")
            
    def process_file(self):
        # Disable button to prevent multiple triggers
        self.process_btn.configure(state="disabled")
        self.status_lbl.configure(text="Processing audio data... Please wait.")
        
        file_to_process = self.file_path.get()
        use_demucs = self.use_demucs_var.get()
        use_spleeter = self.use_spleeter_var.get()
        use_basic_pitch = self.use_basic_pitch_var.get()
        use_magenta = self.use_magenta_var.get()
        use_omnizart = self.use_omnizart_var.get()

        print(f"Starting pipeline for: {file_to_process}")
        print(f"Source separation enabled: {use_demucs}")
        print(f"Spleeter enabled: {use_spleeter}")
        print(f"Basic Pitch enabled: {use_basic_pitch}")
        print(f"Magenta enabled: {use_magenta}")
        print(f"Omnizart enabled: {use_omnizart}")

        # TODO: Inject the ML models and data fusion logic here
        
        # Re-enable after processing is done (placeholder logic)
        self.after(2000, self.processing_mock_complete)

    def processing_mock_complete(self):
        self.status_lbl.configure(text="Processing complete. Ready for next file.")
        self.process_btn.configure(state="normal")

if __name__ == "__main__":
    app = KiviPianoApp()
    app.mainloop()