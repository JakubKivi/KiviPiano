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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
COPY src/kivipiano /opt/kivipiano
COPY requirements-spleeter.txt requirements-magenta.txt /opt/

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && case "$BACKEND" in \
      demucs) \
        python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.2.2+cpu" "torchaudio==2.2.2+cpu" \
        && \
        python -m pip install --no-cache-dir "demucs>=4.0.1,<5" ;; \
      spleeter) \
        python -m pip install --no-cache-dir -r /opt/requirements-spleeter.txt \
        && python -m pip install --no-cache-dir --no-deps "spleeter==2.4.2" ;; \
      basic_pitch) \
        python -m pip install --no-cache-dir "basic-pitch>=0.4.0,<0.5.0" ;; \
      magenta) \
        python -m pip install --no-cache-dir --no-deps "magenta==2.1.3" \
        && python -m pip install --no-cache-dir --no-deps "tensor2tensor==1.15.7" \
        && python -m pip install --no-cache-dir -r /opt/requirements-magenta.txt ;; \
      bytedance) \
        python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.2.2+cpu" \
        && python -m pip install --no-cache-dir "librosa" "piano_transcription_inference>=0.0.4" ;; \
      mt3) \
        git clone --depth 1 https://github.com/magenta/mt3.git /opt/mt3 \
        && python -m pip install --no-cache-dir "jax[cpu]" "nest-asyncio" "pyfluidsynth==1.3.0" "gsutil" \
        && python -m pip install --no-cache-dir -e /opt/mt3 ;; \
      omnizart) \
        python -m pip install --no-cache-dir "tensorflow==2.15.1" \
        && python -m pip install --no-cache-dir "omnizart==0.6.0" ;; \
      *) echo "Unsupported BACKEND: $BACKEND" >&2; exit 2 ;; \
    esac

CMD ["python", "-m", "kivipiano.container_worker"]
