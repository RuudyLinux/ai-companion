"""
File storage for generated audio, voice reference recordings and previews. The DB only
ever stores paths relative to DATA_DIR, so the data directory can move between machines
and absolute paths never reach clients.
"""

import logging
from pathlib import Path

from core.config import settings

log = logging.getLogger("app.storage")


def to_key(path: Path | str) -> str:
    """Absolute path under DATA_DIR -> storage key (posix, relative)."""
    return Path(path).resolve().relative_to(settings.data_dir.resolve()).as_posix()


def resolve(key: str | None) -> Path | None:
    """Storage key -> absolute path, refusing anything that escapes DATA_DIR."""
    if not key:
        return None
    candidate = Path(key)
    if candidate.is_absolute():
        # legacy rows stored absolute paths (migration 0002 rewrites them); only honour
        # one if it still points inside DATA_DIR
        try:
            return resolve(to_key(candidate))
        except ValueError:
            return None
    path = (settings.data_dir / candidate).resolve()
    try:
        path.relative_to(settings.data_dir.resolve())
    except ValueError:
        return None
    return path


def delete(key: str | None) -> None:
    path = resolve(key)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.warning("could not delete stored file", extra={"error_code": "STORAGE_DELETE_FAILED"})


def ensure_dirs() -> None:
    for directory in (
        settings.data_dir,
        settings.voice_audio_dir,
        settings.voice_refs_dir,
        settings.voice_previews_dir,
        settings.data_dir / "tmp",
    ):
        directory.mkdir(parents=True, exist_ok=True)
