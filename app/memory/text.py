"""Tiny lexical helpers for memory matching. Deliberately dependency-free; see
memory/retrieval.py for where embeddings (pgvector) would slot in."""

import re

_WORD = re.compile(r"[\w']+", re.UNICODE)
STOPWORDS = frozenset(
    "a an and are as at be but by for from has have i i'm im in is it its me my of on or our so that the "
    "their them they this to was we were what when where which who will with you your user user's".split()
)


def tokens(text: str) -> set[str]:
    return {w for w in (m.group(0).lower() for m in _WORD.finditer(text or "")) if w not in STOPWORDS and len(w) > 1}


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of content words, 0..1."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
