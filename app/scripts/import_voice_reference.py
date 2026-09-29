"""
Imports an existing recording as a private cloned voice for one user, e.g. a reference
file from before voice cloning moved into the app:

    python scripts/import_voice_reference.py you@example.com path/to/voice.wav "My voice"

The recording is converted to WAV and copied into DATA_DIR/voice_refs; only the
relative storage key is stored in the database.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func  # noqa: E402

from core.config import settings  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import User, Voice, new_id, now  # noqa: E402
from voice.service import store_clone_reference  # noqa: E402


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    email, source = sys.argv[1].strip().lower(), Path(sys.argv[2])
    name = sys.argv[3] if len(sys.argv) == 4 else "My cloned voice"
    if not source.is_file():
        print(f"File not found: {source}")
        sys.exit(1)

    db = SessionLocal()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None:
        print(f"No user found with email {email}")
        sys.exit(1)

    voice_id = new_id()
    key = store_clone_reference(str(source), voice_id)
    db.add(
        Voice(
            id=voice_id,
            name=name,
            category="cloned",
            kind="cloned",
            provider=settings.voice_engine,
            clone_reference=key,
            language="en",
            owner_id=user.id,
            consent_confirmed_at=now(),
        )
    )
    db.commit()
    print(f"Imported {source.name} as '{name}' for {email} (voice id {voice_id})")


if __name__ == "__main__":
    main()
