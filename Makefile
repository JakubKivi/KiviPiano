# Define Python interpreter
PYTHON = python
PIP = pip
PYINSTALLER = pyinstaller

# App name for the executable
APP_NAME = KiviPiano
MAIN_SCRIPT = src/main.py

.PHONY: install run build clean

install:
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) $(MAIN_SCRIPT)

build:
	$(PYINSTALLER) --noconfirm --onedir --windowed --name "$(APP_NAME)" $(MAIN_SCRIPT)

clean:
	rm -rf build/
	rm -rf dist/
	rm -f $(APP_NAME).spec
	rm -rf __pycache__/