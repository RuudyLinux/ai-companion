# CPU image: web app + worker + local Whisper STT. Pair with VOICE_ENGINE=inworld (cloud TTS).
# For local GPU TTS (xtts/f5tts) build from an NVIDIA CUDA base and install requirements/gpu.txt.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    DATA_DIR=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements/ requirements/
RUN pip install -r requirements/production.txt

COPY . .
RUN useradd --create-home --uid 10001 companion \
    && mkdir -p /data \
    && chown -R companion:companion /data
USER companion

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live').status == 200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
