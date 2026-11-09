"""Ensure Python 3.10 is installed so ``make install`` can set up Magenta.

Magenta needs Python 3.10 (its TensorFlow 2.9 dependencies conflict with the
Python 3.11 environment used by the rest of the app), so it lives in its own
``.venv-magenta``. This script removes the last manual step: it installs
Python 3.10 automatically when the ``py`` launcher cannot find it, first via
``winget`` and then via the official python.org installer.
"""

import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PYTHON_VERSION = "3.10.11"
INSTALLER_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-amd64.exe"
)


def _py_launcher() -> str | None:
    return shutil.which("py")


def python310_available() -> bool:
    launcher = _py_launcher()
    if launcher is None:
        return False
    result = subprocess.run(
        [launcher, "-3.10", "--version"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd).returncode


def install_with_winget() -> bool:
    if shutil.which("winget") is None:
        return False
    code = _run(
        [
            "winget",
            "install",
            "--id",
            "Python.Python.3.10",
            "--scope",
            "user",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
    )
    return code == 0 and python310_available()


def install_with_official_installer() -> bool:
    installer = (
        Path(tempfile.gettempdir()) / f"python-{PYTHON_VERSION}-amd64.exe"
    )
    print(f"Downloading {INSTALLER_URL}", flush=True)
    urllib.request.urlretrieve(INSTALLER_URL, installer)
    code = _run(
        [
            str(installer),
            "/quiet",
            "InstallAllUsers=0",
            "PrependPath=0",
            "Include_launcher=1",
            "Include_test=0",
        ]
    )
    return code == 0 and python310_available()


def main() -> int:
    if python310_available():
        print("Python 3.10 is already available.", flush=True)
        return 0

    print("Python 3.10 is missing. Installing it now...", flush=True)
    try:
        if install_with_winget():
            print("Python 3.10 installed via winget.", flush=True)
            return 0
        print("winget did not work; using the official python.org installer.", flush=True)
        if install_with_official_installer():
            print("Python 3.10 installed from python.org.", flush=True)
            return 0
    except OSError as exc:
        print(f"ERROR: could not install Python 3.10: {exc}", file=sys.stderr, flush=True)

    print(
        "ERROR: could not install Python 3.10 automatically.\n"
        "Install Python 3.10 manually (https://www.python.org/downloads/) "
        "and run `make install` again.",
        file=sys.stderr,
        flush=True,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
