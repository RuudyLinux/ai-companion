"""
Audio upload validation shared by STT and voice cloning.

Checks, in order: declared content type, size (streamed, never fully in memory),
magic bytes of the actual content, then a full decode with PyAV to prove the file is
real audio and to measure its duration. The temp file is always removed on exit.
"""

import os
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool

from core.config import settings
from core.errors import AppError, PayloadTooLarge

CHUNK = 1024 * 1024

ALLOWED_CONTENT_TYPES = {
    "audio/webm", "video/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave",
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/x-m4a", "audio/m4a", "audio/aac", "audio/flac",
    "audio/x-flac", "application/octet-stream",
}

SUFFIX_FOR_KIND = {"wav": ".wav", "webm": ".webm", "ogg": ".ogg", "flac": ".flac", "mp3": ".mp3", "mp4": ".m4a"}


class InvalidAudio(AppError):
    status_code = 422
    code = "INVALID_AUDIO"
    message = "The uploaded file isn't a supported audio recording."


class UnsupportedMediaType(AppError):
    status_code = 415
    code = "UNSUPPORTED_MEDIA_TYPE"
    message = "Unsupported file type. Upload WAV, WebM, OGG, MP3, M4A or FLAC audio."


class AudioTooLong(AppError):
    status_code = 422
    code = "AUDIO_TOO_LONG"


class AudioTooShort(AppError):
    status_code = 422
    code = "AUDIO_TOO_SHORT"


def sniff_audio_kind(head: bytes) -> str | None:
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    if len(head) >= 8 and head[4:8] == b"ftyp":
        return "mp4"
    return None


def probe_duration_seconds(path: str) -> float:
    """Decodes the whole audio stream (proves it's genuine audio) and returns its length.
    MediaRecorder WebM files often carry no duration header, so samples are counted."""
    import av  # installed with faster-whisper

    try:
        with av.open(path) as container:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                raise InvalidAudio("The file contains no audio track.")
            samples = 0
            rate = stream.rate or 0
            for frame in container.decode(stream):
                samples += frame.samples
                rate = frame.sample_rate or rate
                if rate and samples / rate > settings.max_audio_seconds + 1:
                    break  # already too long; no need to decode the rest
    except InvalidAudio:
        raise
    except Exception as exc:  # PyAV raises many different error types for corrupt input
        raise InvalidAudio() from exc
    if not rate or samples == 0:
        raise InvalidAudio("The recording is empty.")
    return samples / rate


@dataclass
class ValidatedAudio:
    path: str
    kind: str
    size_bytes: int
    duration_seconds: float


@asynccontextmanager
async def validated_audio_upload(
    upload: UploadFile,
    *,
    max_seconds: int | None = None,
    min_seconds: float = 0.2,
):
    """Yields a ValidatedAudio whose temp file is deleted when the block exits."""
    content_type = (upload.content_type or "application/octet-stream").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedMediaType()

    tmp_dir = settings.data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=tmp_dir, prefix="upload-")
    try:
        size = 0
        head = b""
        with os.fdopen(fd, "wb") as out:
            while chunk := await upload.read(CHUNK):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise PayloadTooLarge(f"Uploads are limited to {settings.max_upload_mb} MB.")
                if len(head) < 16:
                    head += chunk[: 16 - len(head)]
                out.write(chunk)

        if size == 0:
            raise InvalidAudio("The upload is empty.")
        kind = sniff_audio_kind(head)
        if kind is None:
            raise InvalidAudio()

        final_path = tmp_path + SUFFIX_FOR_KIND[kind]  # decoders and Whisper use the extension as a hint
        os.replace(tmp_path, final_path)
        tmp_path = final_path

        duration = await run_in_threadpool(probe_duration_seconds, tmp_path)  # CPU-bound decode
        limit = max_seconds or settings.max_audio_seconds
        if duration > limit:
            raise AudioTooLong(f"Recordings are limited to {limit} seconds.")
        if duration < min_seconds:
            raise AudioTooShort(f"The recording must be at least {min_seconds:g} seconds long.")

        yield ValidatedAudio(path=tmp_path, kind=kind, size_bytes=size, duration_seconds=duration)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
