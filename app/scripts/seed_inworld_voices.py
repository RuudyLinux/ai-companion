"""
Seeds the voices table from Inworld's real voice list (269 SYSTEM presets + your
cloned voice). No preview audio is pre-generated here — Inworld is a paid API, so
generating 269 preview clips upfront would burn real quota/cost for voices nobody
ever previews. Previews are generated lazily on first click instead (see
routers/voice_library.py's /api/voices/<id>/preview endpoint).

Usage: venv\\Scripts\\python.exe scripts\\seed_inworld_voices.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal, Base, engine
from models import Voice
from voice.engines.inworld_engine import InworldEngine

Base.metadata.create_all(bind=engine)


def main():
    db = SessionLocal()

    if db.query(Voice).count() > 0:
        print("Voices table is not empty — clear it first if you want to reseed.")
        return

    engine_client = InworldEngine()
    voices = engine_client.list_voices()
    print(f"Fetched {len(voices)} voices from Inworld")

    for v in voices:
        kind = "cloned" if v["source"] != "SYSTEM" else "builtin"
        category = "cloned" if kind == "cloned" else f"{v.get('gender', 'unknown')} · {v.get('languageCode', '?')}"

        db.add(
            Voice(
                name=v["displayName"],
                category=category,
                kind=kind,
                speaker_ref=v["voiceId"],
                preview_audio_path=None,  # generated lazily on first preview click
            )
        )

    db.commit()
    print(f"Seeded {len(voices)} voices.")


if __name__ == "__main__":
    main()
