"""
DSP-based emotion/voice-changer presets. No trained emotional-TTS model exists locally
(none of the bundled datasets have emotion-labeled speech-synthesis training pairs), so
this simulates emotion/style via signal processing on top of whatever voice (cloned or
library) already generated the base audio.

IMPORTANT: pitch/speed changes use resample-based speed shifting (like a tape/turntable
speed knob — pitch and duration move together), not librosa's STFT phase-vocoder
pitch_shift/time_stretch. The phase-vocoder approach was tried first and reliably
produced robotic/"multiple voices" chorus artifacts on speech, confirmed by user
testing — resample-based shifting has none of that (it's just resampling, no phase
reconstruction to go wrong), at the cost of not being able to change pitch and tempo
independently. That trade-off is fine here since we're simulating mood, not doing
professional audio production.

Honest limitation: these are audio effects, not separately trained AI voices.
"""

import numpy as np
import librosa
import soundfile as sf
from scipy.signal import butter, sosfilt


def _speed(y, sr, rate):
    """rate > 1 = faster + higher pitch, rate < 1 = slower + lower pitch. Artifact-free."""
    if rate == 1.0:
        return y
    target_sr = sr / rate
    return librosa.resample(y, orig_sr=sr, target_sr=target_sr)


def _gain(y, db):
    if db == 0:
        return y
    return y * (10 ** (db / 20))


def _bandpass(y, sr, low, high):
    sos = butter(4, [low, high], btype="band", fs=sr, output="sos")
    return sosfilt(sos, y)


def _ring_mod(y, sr, freq):
    t = np.arange(len(y)) / sr
    carrier = np.sin(2 * np.pi * freq * t)
    return y * carrier * 1.6


def _echo(y, sr, delay_ms, decay):
    delay_samples = int(sr * delay_ms / 1000)
    out = np.copy(y)
    if delay_samples < len(y):
        out[delay_samples:] += y[: len(y) - delay_samples] * decay
    return out


def _normalize(y):
    peak = np.max(np.abs(y)) or 1.0
    return y / peak * 0.95


# Each preset is a list of (fn_name, kwargs) applied in order.
EMOTION_EFFECTS = {
    "happy": [("speed", {"rate": 1.05}), ("gain", {"db": 1})],
    "sad": [("speed", {"rate": 0.92}), ("gain", {"db": -1.5})],
    "excited": [("speed", {"rate": 1.10}), ("gain", {"db": 1.5})],
    "angry": [("speed", {"rate": 1.05}), ("gain", {"db": 2})],
    "calm": [("speed", {"rate": 0.95}), ("gain", {"db": -0.5})],
    "friendly": [("speed", {"rate": 1.02})],
    "romantic": [("speed", {"rate": 0.92}), ("gain", {"db": -1})],
    "serious": [("speed", {"rate": 0.97})],
    "motivational": [("speed", {"rate": 1.06}), ("gain", {"db": 1.5})],
    "confident": [("speed", {"rate": 1.02}), ("gain", {"db": 1})],
    "emotional": [("speed", {"rate": 0.90}), ("gain", {"db": -1})],
    "whisper": [("gain", {"db": -9}), ("bandpass", {"low": 300, "high": 6000})],
    "fear": [("speed", {"rate": 1.08}), ("gain", {"db": -1})],
    "surprised": [("speed", {"rate": 1.06}), ("gain", {"db": 1.5})],
    "funny": [("speed", {"rate": 1.15})],
    "sleepy": [("speed", {"rate": 0.85}), ("gain", {"db": -2})],
}

VOICE_CHANGER_STYLES = {
    "deep": [("speed", {"rate": 0.82})],
    "soft": [("gain", {"db": -3}), ("bandpass", {"low": 80, "high": 6000})],
    "cartoon": [("speed", {"rate": 1.35})],
    "radio": [("bandpass", {"low": 300, "high": 3400}), ("gain", {"db": 3})],
    "robot": [("ring_mod", {"freq": 45}), ("bandpass", {"low": 100, "high": 8000})],
    "child": [("speed", {"rate": 1.25})],
    "elder": [("speed", {"rate": 0.80})],
    "cinematic": [("speed", {"rate": 0.97}), ("echo", {"delay_ms": 150, "decay": 0.2})],
    "podcast": [("bandpass", {"low": 80, "high": 12000}), ("gain", {"db": 2})],
    "story_narrator": [("speed", {"rate": 0.93}), ("echo", {"delay_ms": 100, "decay": 0.12})],
}

_FN_MAP = {
    "speed": lambda y, sr, **kw: _speed(y, sr, kw["rate"]),
    "gain": lambda y, sr, **kw: _gain(y, kw["db"]),
    "bandpass": lambda y, sr, **kw: _bandpass(y, sr, kw["low"], kw["high"]),
    "ring_mod": lambda y, sr, **kw: _ring_mod(y, sr, kw["freq"]),
    "echo": lambda y, sr, **kw: _echo(y, sr, kw["delay_ms"], kw["decay"]),
}


def apply_chain(input_path: str, output_path: str, chain: list[tuple[str, dict]]) -> None:
    """Applies an explicit (fn_name, kwargs) DSP chain to a wav file. Empty chain = passthrough copy."""
    y, sr = librosa.load(input_path, sr=None, mono=True)

    for fn_name, kwargs in chain:
        y = _FN_MAP[fn_name](y, sr, **kwargs)
    if chain:
        y = _normalize(y)

    sf.write(output_path, y, sr)


def apply_preset(input_path: str, output_path: str, preset_name: str, presets: dict) -> bool:
    """Applies a named DSP preset to a wav file. Returns False if preset unknown (no-op copy)."""
    chain = presets.get(preset_name)
    apply_chain(input_path, output_path, chain or [])
    return chain is not None
