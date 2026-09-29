"""
One-time seed: generates a short preview clip for every XTTS-v2 built-in speaker (58 of
them) plus the cloned Helly voice, measures rough pitch to bucket builtin speakers into
Male-leaning/Female-leaning (no metadata ships with the model — this is a measured
heuristic, not verified ground truth), and inserts everything into the voices table.

The requested categories that aren't measurable from a raw voice alone (child, elder,
robotic, anime, news anchor, narrator, deep, soft, cinematic, podcast, ...) live as
DSP *style* presets applied on top of any base voice (see voice/effects.py) rather than
as separate builtin speakers — that's the honest way to deliver that variety without
fabricating unverifiable labels for opaque studio voice names.

Usage: venv\\Scripts\\python.exe scripts\\seed_voices.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import librosa

from database import SessionLocal, Base, engine
from models import Voice
from voice.xtts import synthesize, builtin_speaker_names, CLONE_REFERENCE_WAV

Base.metadata.create_all(bind=engine)

PREVIEW_DIR = Path(__file__).resolve().parent.parent / "static" / "previews"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

PREVIEW_TEXT = "Hello, this is a preview of my voice."
PITCH_SPLIT_HZ = 165  # rough male/female median-pitch split point


def measure_median_pitch(wav_path: str) -> float:
    y, sr = librosa.load(wav_path, sr=None, mono=True)
    f0, voiced_flag, _ = librosa.pyin(y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr)
    voiced = f0[voiced_flag] if voiced_flag is not None else f0
    voiced = voiced[~np.isnan(voiced)]
    return float(np.median(voiced)) if len(voiced) else 0.0


def main():
    db = SessionLocal()

    existing_refs = {v.speaker_ref for v in db.query(Voice).all()}

    if CLONE_REFERENCE_WAV not in existing_refs:
        print("Seeding cloned voice...")
        cloned_preview = PREVIEW_DIR / "cloned_helly.wav"
        synthesize(PREVIEW_TEXT, str(cloned_preview), language="en", speaker_wav=CLONE_REFERENCE_WAV)
        db.add(
            Voice(
                name="My Cloned Voice",
                category="cloned",
                kind="cloned",
                speaker_ref=CLONE_REFERENCE_WAV,
                preview_audio_path=f"/static/previews/{cloned_preview.name}",
            )
        )
        db.commit()

    all_speakers = builtin_speaker_names()
    remaining = [n for n in all_speakers if n not in existing_refs]
    print(f"Seeding {len(remaining)} remaining builtin XTTS speakers (of {len(all_speakers)})...")

    for i, name in enumerate(remaining):
        safe_name = name.lower().replace(" ", "_")
        preview_path = PREVIEW_DIR / f"{safe_name}.wav"
        try:
            synthesize(PREVIEW_TEXT, str(preview_path), language="en", speaker_name=name)
            pitch = measure_median_pitch(str(preview_path))
            category = "male" if pitch and pitch < PITCH_SPLIT_HZ else "female"
        except Exception as e:
            print(f"  skipped {name}: {e}")
            continue

        db.add(
            Voice(
                name=name,
                category=category,
                kind="builtin",
                speaker_ref=name,
                preview_audio_path=f"/static/previews/{preview_path.name}",
            )
        )
        db.commit()
        print(f"  [{i + 1}/{len(remaining)}] {name.encode('ascii', 'replace').decode()} -> {category} (median pitch {pitch:.0f}Hz)")

    print("Done.")


if __name__ == "__main__":
    main()
