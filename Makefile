# Keep the desktop app separate from isolated model containers.
PYTHON311 = py -3.11
VENV_DIR = .venv
VENV_PYTHON = $(VENV_DIR)/Scripts/python.exe
INSTALL_MARKER = $(VENV_DIR)/.installed
DOCKER_INSTALL_MARKER = .docker-installed

MAIN_SCRIPT = src/main.py

.PHONY: install prepare-models docker-build run test clean

$(INSTALL_MARKER): pyproject.toml requirements.txt
	$(PYTHON311) -m venv $(VENV_DIR)
	$(VENV_PYTHON) -m pip install -r requirements.txt
	$(VENV_PYTHON) -m pip install --no-deps -e .
	$(VENV_PYTHON) -c "from pathlib import Path; Path('$(INSTALL_MARKER)').touch()"

install: $(INSTALL_MARKER) prepare-models

# Always run (idempotent): makes sure every model is present even when the
# install markers already exist, so a fresh `make install` can never
# silently skip a model download.
prepare-models: $(INSTALL_MARKER) $(DOCKER_INSTALL_MARKER)
	$(VENV_PYTHON) -m kivipiano.prepare_models

$(DOCKER_INSTALL_MARKER): $(INSTALL_MARKER) docker-compose.yml docker/Dockerfile $(wildcard src/kivipiano/*.py) requirements-magenta.txt requirements-spleeter.txt
	docker compose build
	$(VENV_PYTHON) -c "from pathlib import Path; Path('$(DOCKER_INSTALL_MARKER)').touch()"

docker-build: $(DOCKER_INSTALL_MARKER)

run: install
	$(VENV_PYTHON) $(MAIN_SCRIPT)

test: $(INSTALL_MARKER)
	$(VENV_PYTHON) -m unittest discover -s tests -v

clean:
	rm -rf __pycache__/