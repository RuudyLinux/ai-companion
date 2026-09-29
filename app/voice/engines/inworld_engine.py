"""
Inworld AI cloud TTS engine (cloud_production mode). Like ElevenLabs, cloning needs a
one-time registration call (POST /voices/v1/voices:clone -> voiceId) that's cached to
disk so we don't re-register the same reference file on every synthesis call.

Auth quirk: INWORLD_API_KEY is *already* a base64-encoded "key:secret" pair (Inworld
issues it that way) — the Authorization header is literally "Basic {the raw key
string}", not a re-encoded value.
"""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

from voice.engine_base import VoiceEngine

API_BASE = "https://api.inworld.ai"
VOICE_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "inworld_voice_cache.json"
TRANSCRIBE_CLI = Path(__file__).resolve().parent.parent.parent / "scripts" / "transcribe_cli.py"
MODEL_ID = "inworld-tts-2"
SAMPLE_RATE = 24000

# Two different formats for two different endpoints (confirmed from Inworld's own docs
# and example scripts, not a guess): the clone endpoint wants "EN_US" (underscore,
# uppercase), the TTS endpoint wants BCP-47 "en-US" (hyphenated).
_LANG_TO_CLONE_CODE = {
    "en": "EN_US", "hi": "HI_IN", "gu": "GU_IN", "mr": "MR_IN", "bn": "BN_IN",
    "ta": "TA_IN", "te": "TE_IN", "ml": "ML_IN", "pa": "PA_IN", "ur": "UR_PK",
    "es": "ES_ES", "fr": "FR_FR", "de": "DE_DE", "it": "IT_IT", "pt": "PT_PT",
    "ja": "JA_JP", "ko": "KO_KR", "zh-cn": "ZH_CN", "ar": "AR_SA", "ru": "RU_RU",
}
_LANG_TO_BCP47 = {
    "en": "en-US", "hi": "hi-IN", "gu": "gu-IN", "mr": "mr-IN", "bn": "bn-IN",
    "ta": "ta-IN", "te": "te-IN", "ml": "ml-IN", "pa": "pa-IN", "ur": "ur-PK",
    "es": "es-ES", "fr": "fr-FR", "de": "de-DE", "it": "it-IT", "pt": "pt-PT",
    "ja": "ja-JP", "ko": "ko-KR", "zh-cn": "zh-CN", "ar": "ar-SA", "ru": "ru-RU",
}


def _transcribe_for_clone(speaker_wav: str) -> str:
    """Optional but improves clone fidelity per Inworld's docs. Best-effort — cloning
    still works without it, so any failure here is swallowed rather than raised."""
    try:
        result = subprocess.run(
            [sys.executable, str(TRANSCRIBE_CLI), speaker_wav], capture_output=True, timeout=120
        )
        return result.stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


class InworldMisconfigured(RuntimeError):
    pass


class InworldEngine(VoiceEngine):
    name = "cloud_production"
    clone_needs_raw_file = False

    def __init__(self):
        self.api_key = os.environ.get("INWORLD_API_KEY", "").strip()

    def _require_key(self):
        if not self.api_key:
            raise InworldMisconfigured("INWORLD_API_KEY is not set — cloud_production voice mode needs it in .env")

    def _headers(self, json_body=True):
        headers = {"Authorization": f"Basic {self.api_key}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _load_cache(self) -> dict:
        if VOICE_CACHE_PATH.exists():
            return json.loads(VOICE_CACHE_PATH.read_text())
        return {}

    def _save_cache(self, cache: dict):
        VOICE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        VOICE_CACHE_PATH.write_text(json.dumps(cache, indent=2))

    def _get_or_create_cloned_voice_id(self, speaker_wav: str, lang_code: str) -> str:
        self._require_key()
        cache = self._load_cache()
        if speaker_wav in cache:
            return cache[speaker_wav]

        with open(speaker_wav, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()

        sample = {"audioData": audio_b64}
        transcription = _transcribe_for_clone(speaker_wav)
        if transcription:
            sample["transcription"] = transcription

        resp = requests.post(
            f"{API_BASE}/voices/v1/voices:clone",
            headers=self._headers(),
            json={
                "displayName": "AI Companion Cloned Voice",
                "langCode": _LANG_TO_CLONE_CODE.get(lang_code, "EN_US"),
                "voiceSamples": [sample],
            },
            timeout=60,
        )
        resp.raise_for_status()
        voice_id = resp.json()["voice"]["voiceId"]
        cache[speaker_wav] = voice_id
        self._save_cache(cache)
        return voice_id

    def synthesize(self, text, out_path, language="en", speaker_wav=None, speaker_name=None):
        self._require_key()

        if speaker_wav:
            voice_id = self._get_or_create_cloned_voice_id(speaker_wav, language)
        elif speaker_name:
            voice_id = speaker_name
        else:
            raise ValueError("synthesize() requires speaker_wav or speaker_name")

        resp = requests.post(
            f"{API_BASE}/tts/v1/voice",
            headers=self._headers(),
            json={
                "text": text,
                "voiceId": voice_id,
                "modelId": MODEL_ID,
                "language": _LANG_TO_BCP47.get(language, "en-US"),
                "audioConfig": {"audioEncoding": "WAV", "sampleRateHertz": SAMPLE_RATE},
            },
            timeout=120,
        )
        resp.raise_for_status()
        audio_bytes = base64.b64decode(resp.json()["audioContent"])

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(audio_bytes)  # audioEncoding=WAV means this already has a full WAV container header

    def list_voices(self) -> list[dict]:
        """Full metadata for every voice on the account: 269 SYSTEM presets (name,
        gender, ageGroup, description, tags, languageCode) plus any cloned (IVC) ones."""
        self._require_key()
        resp = requests.get(f"{API_BASE}/voices/v1/voices", headers=self._headers(json_body=False), timeout=30)
        resp.raise_for_status()
        return resp.json().get("voices", [])

    def builtin_speakers(self) -> list[str]:
        return [v["voiceId"] for v in self.list_voices() if v["source"] == "SYSTEM"]

    def supports_language(self, xtts_style_code):
        return xtts_style_code in _LANG_TO_BCP47
