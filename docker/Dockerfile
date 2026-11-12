# Python 3.10 is the common denominator across backends: Magenta pins
# TensorFlow 2.9.1, which has no Python 3.11 wheels. The desktop app runs in
# its own `.venv` on Python 3.11; these container runtimes are fully isolated.
FROM python:3.10-slim

ARG BACKEND
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt \
    HOME=/models/home \
    HF_HOME=/models/huggingface \
    HF_HUB_OFFLINE=1 \
    TF_CPP_MIN_LOG_LEVEL=2

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        git \
        libasound2-dev \
        libfluidsynth3 \
        libjack-dev \
        libsndfile1 \
        pkg-config \
        sox \
        vamp-plugin-sdk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
# Only the (rarely changing) requirements files feed the heavy pip-install
# layer. The app source is copied afterwards so that editing a source file
# never invalidates the cached model-dependency layers and triggers a full
# multi-minute rebuild of all six images.
COPY requirements-spleeter.txt requirements-magenta.txt /opt/

RUN python -m pip install --no-cache-dir --upgrade pip wheel "setuptools<81" \
    && case "$BACKEND" in \
      demucs) \
        python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.2.2+cpu" "torchaudio==2.2.2+cpu" \
        && \
        python -m pip install --no-cache-dir "numpy<2" "demucs>=4.0.1,<5" ;; \
      spleeter) \
        python -m pip install --no-cache-dir -r /opt/requirements-spleeter.txt \
        && python -m pip install --no-cache-dir --no-deps "spleeter==2.4.2" ;; \
      basic_pitch) \
        python -m pip install --no-cache-dir "numpy<2" "basic-pitch>=0.4.0,<0.5.0" ;; \
      magenta) \
        python -m pip install --no-cache-dir --no-deps "magenta==2.1.3" \
        && python -m pip install --no-cache-dir --no-deps "tensor2tensor==1.15.7" \
        && python -m pip install --no-cache-dir -r /opt/requirements-magenta.txt ;; \
      bytedance) \
        python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.2.2+cpu" \
        && python -m pip install --no-cache-dir "numpy<2" "pretty-midi" "librosa" "piano_transcription_inference>=0.0.4" ;; \
      omnizart) \
        python -m pip install --no-cache-dir "cython" "numpy<2" \
        && python -m pip install --no-cache-dir --no-build-isolation "numpy<2" "omnizart==0.6.0" \
        && python -c 'import urllib.request, os; d="/usr/local/lib/python3.10/site-packages/omnizart/checkpoints/music/music_piano/variables"; os.makedirs(d, exist_ok=True); urllib.request.urlretrieve("https://github.com/Music-and-Culture-Technology-Lab/omnizart/releases/download/checkpoints-20211001/music_piano@variables.data-00000-of-00001", os.path.join(d, "variables.data-00000-of-00001"))' ;; \
      *) echo "Unsupported BACKEND: $BACKEND" >&2; exit 2 ;; \
    esac

COPY src/kivipiano /opt/kivipiano

# Legacy-package compatibility shims (madmom on Python 3.10 / numpy 1.x).
COPY docker/sitecustomize.py /usr/local/lib/python3.10/site-packages/sitecustomize.py

CMD ["python", "-m", "kivipiano.container_worker"]
