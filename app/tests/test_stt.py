import subprocess

import pytest

import routers.speech as speech
import voice.stt_runner as stt_runner
from conftest import wav_bytes
from core.uploads import sniff_audio_kind
from voice.stt_runner import STTError, STTTimeout, run_transcription


@pytest.fixture
def transcribe_ok(monkeypatch):
    calls = []

    def fake(path):
        calls.append(path)
        return {"text": "hello world", "language": "en"}

    monkeypatch.setattr(speech, "run_transcription", fake)
    return calls


def test_transcribes_valid_audio_and_cleans_up(make_client, transcribe_ok):
    client = make_client("a@example.com")
    res = client.post("/api/stt", files={"audio": ("rec.wav", wav_bytes(1.5), "audio/wav")})
    assert res.status_code == 200
    assert res.json() == {"text": "hello world", "language": "en", "duration": 1.5}
    import os

    assert not os.path.exists(transcribe_ok[0])  # temp file removed


def test_rejects_non_audio(make_client, transcribe_ok):
    client = make_client("a@example.com")
    res = client.post("/api/stt", files={"audio": ("x.wav", b"<?php system($_GET['c']); ?>", "audio/wav")})
    assert res.status_code == 422 and res.json()["error"]["code"] == "INVALID_AUDIO"
    assert transcribe_ok == []


def test_rejects_wrong_content_type(make_client, transcribe_ok):
    client = make_client("a@example.com")
    res = client.post("/api/stt", files={"audio": ("x.html", wav_bytes(), "text/html")})
    assert res.status_code == 415


def test_rejects_oversized_upload(make_client, transcribe_ok):
    client = make_client("a@example.com")
    res = client.post("/api/stt", files={"audio": ("x.wav", b"RIFF" + b"\0" * (3 * 1024 * 1024), "audio/wav")})
    assert res.status_code == 413
    assert transcribe_ok == []


def test_rejects_too_long_audio(make_client, transcribe_ok, monkeypatch):
    client = make_client("a@example.com")
    import dataclasses

    import core.uploads as uploads

    monkeypatch.setattr(uploads, "settings", dataclasses.replace(uploads.settings, max_audio_seconds=1))
    res = client.post("/api/stt", files={"audio": ("x.wav", wav_bytes(2.5), "audio/wav")})
    assert res.status_code == 422 and res.json()["error"]["code"] == "AUDIO_TOO_LONG"


def test_requires_authentication(client, transcribe_ok):
    res = client.post("/api/stt", files={"audio": ("x.wav", wav_bytes(), "audio/wav")})
    assert res.status_code == 401


def test_sniffs_common_formats():
    assert sniff_audio_kind(wav_bytes()[:16]) == "wav"
    assert sniff_audio_kind(b"\x1a\x45\xdf\xa3" + b"\0" * 12) == "webm"
    assert sniff_audio_kind(b"OggS" + b"\0" * 12) == "ogg"
    assert sniff_audio_kind(b"ID3" + b"\0" * 13) == "mp3"
    assert sniff_audio_kind(b"\0\0\0\x20ftypM4A " + b"\0" * 4) == "mp4"
    assert sniff_audio_kind(b"MZ\x90\x00" + b"\0" * 12) is None


def _completed(returncode, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_runner_checks_return_code(monkeypatch):
    monkeypatch.setattr(stt_runner.subprocess, "run", lambda *a, **k: _completed(2, stderr=b"CUDA error at C:\\x"))
    with pytest.raises(STTError) as info:
        run_transcription("x.wav")
    assert "CUDA" not in info.value.message


def test_runner_timeout(monkeypatch):
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="whisper", timeout=1)

    monkeypatch.setattr(stt_runner.subprocess, "run", slow)
    with pytest.raises(STTTimeout):
        run_transcription("x.wav")


def test_runner_parses_json_output(monkeypatch):
    monkeypatch.setattr(
        stt_runner.subprocess, "run", lambda *a, **k: _completed(0, stdout='{"text": " héllo ", "language": "fr"}'.encode())
    )
    assert run_transcription("x.wav") == {"text": "héllo", "language": "fr"}


def test_stt_failure_maps_to_api_error(make_client, monkeypatch):
    client = make_client("a@example.com")
    monkeypatch.setattr(stt_runner.subprocess, "run", lambda *a, **k: _completed(2))
    monkeypatch.setattr(speech, "run_transcription", run_transcription)
    res = client.post("/api/stt", files={"audio": ("x.wav", wav_bytes(), "audio/wav")})
    assert res.status_code == 502 and res.json()["error"]["code"] == "STT_FAILED"
