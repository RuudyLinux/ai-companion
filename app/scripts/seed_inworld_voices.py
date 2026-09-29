"""
Seeds the voices table from Inworld's SYSTEM voice list (269 presets). No preview audio
is pre-generated here — Inworld is a paid API, so generating 269 preview clips upfront
would burn real quota/cost for voices nobody ever previews. Previews are generated
lazily on first click instead (see routers/voice_library.py).

Account-level cloned (IVC) voices are not imported as shared voices: a cloned voice
must belong to one user. Users clone their own voice in the Voice Library.

Usage: python scripts/seed_inworld_voices.py   (run `alembic upgrade head` first)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal  # noqa: E402
from models import Voice  # noqa: E402
from voice.engines.inworld_engine import InworldEngine  # noqa: E402


def main():
    db = SessionLocal()
    existing = {
        v.provider_voice_id
        for v in db.query(Voice).filter(Voice.provider == "inworld", Voice.kind == "builtin").all()
    }

    voices = [v for v in InworldEngine().list_voices() if v.get("source") == "SYSTEM"]
    print(f"Fetched {len(voices)} system voices from Inworld")

    added = 0
    for v in voices:
        if v["voiceId"] in existing:
            continue
        db.add(
            Voice(
                name=v["displayName"],
                category=f"{v.get('gender', 'unknown')} · {v.get('languageCode', '?')}",
                kind="builtin",
                provider="inworld",
                provider_voice_id=v["voiceId"],
                language=(v.get("languageCode") or "en")[:2].lower(),
                preview_audio_path=None,  # generated lazily on first preview click
            )
        )
        added += 1

    db.commit()
    print(f"Seeded {added} new voices ({len(voices) - added} already present).")


if __name__ == "__main__":
    main()
