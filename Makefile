# Keep the app and all separator dependencies in one Python environment.
PYTHON311 = py -3.11
VENV_DIR = .venv
VENV_PYTHON = $(VENV_DIR)/Scripts/python.exe
INSTALL_MARKER = $(VENV_DIR)/.installed
MAGENTA_VENV_DIR = .venv-magenta
MAGENTA_PYTHON = $(MAGENTA_VENV_DIR)/Scripts/python.exe
MAGENTA_INSTALL_MARKER = $(MAGENTA_VENV_DIR)/.installed

# App name for the executable
APP_NAME = KiviPiano
MAIN_SCRIPT = src/main.py

.PHONY: install install-spleeter install-magenta prepare-models run build test clean

$(INSTALL_MARKER): pyproject.toml requirements.txt requirements-spleeter.txt
	$(PYTHON311) -m venv $(VENV_DIR)
	$(VENV_PYTHON) -m pip install -r requirements.txt -r requirements-spleeter.txt
	$(VENV_PYTHON) -m pip install --no-deps spleeter==2.4.2
	$(VENV_PYTHON) -m pip install --no-deps -e .
	$(VENV_PYTHON) -c "from pathlib import Path; Path('$(INSTALL_MARKER)').touch()"

install: $(INSTALL_MARKER) prepare-models $(MAGENTA_INSTALL_MARKER)

# Always run (idempotent): makes sure every model is present even when the
# `.venv/.installed` marker already exists, so a fresh `make install` can never
# silently skip a model download.
prepare-models: $(INSTALL_MARKER)
	$(VENV_PYTHON) -m kivipiano.prepare_models

install-spleeter: install

# Google Magenta needs Python 3.10 (its TensorFlow 2.9 conflicts with the
# Python 3.11 environment used above), so it lives in its own `.venv-magenta`.
# `make install` pulls it in automatically, installing Python 3.10 if needed;
# `make install-magenta` is just a convenience target to (re)install Magenta.
$(MAGENTA_INSTALL_MARKER): requirements-magenta.txt
	py -3.11 scripts/install_python310.py
	py -3.10 -m venv $(MAGENTA_VENV_DIR)
	$(MAGENTA_PYTHON) -m pip install --no-deps magenta==2.1.3
	$(MAGENTA_PYTHON) -m pip install --no-deps tensor2tensor==1.15.7
	$(MAGENTA_PYTHON) -m pip install -r requirements-magenta.txt
	$(MAGENTA_PYTHON) -c "from pathlib import Path; Path('$(MAGENTA_INSTALL_MARKER)').touch()"

install-magenta: $(MAGENTA_INSTALL_MARKER)

run: install
	$(VENV_PYTHON) $(MAIN_SCRIPT)

build: install
	$(VENV_PYTHON) -m PyInstaller --noconfirm --onedir --windowed --collect-all demucs --collect-all spleeter --collect-all tensorflow --collect-all imageio_ffmpeg --collect-all yt_dlp --collect-all basic_pitch --collect-all pretty_midi --name "$(APP_NAME)" $(MAIN_SCRIPT)

test: $(INSTALL_MARKER)
	$(VENV_PYTHON) -m unittest discover -s tests -v

clean:
	rm -rf build/
	rm -rf dist/
	rm -f $(APP_NAME).spec
	rm -rf __pycache__/