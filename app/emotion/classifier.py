import re
from functools import lru_cache
from pathlib import Path

import joblib

from emotion.label_mapping import OUR_LABELS

MODEL_PATH = Path(__file__).resolve().parent.parent / "models_store" / "emotion_classifier.joblib"

# "stressed" has zero training examples in either source dataset (neither GoEmotions
# nor the EmpatheticDialogues set uses that exact label) — pragmatic keyword patch
# rather than leaving the class permanently unreachable.
STRESS_KEYWORDS = re.compile(
    r"\b(stress(ed)?|overwhelm(ed|ing)?|deadline|burn(ed|t)? out|too much (going on|to do)|swamped)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _load():
    if not MODEL_PATH.exists():
        return None
    artifact = joblib.load(MODEL_PATH)
    return artifact["vectorizer"], artifact["model"]


def classify_emotion(text: str) -> str:
    if STRESS_KEYWORDS.search(text):
        return "stressed"

    loaded = _load()
    if loaded is None:
        return "neutral"  # model not trained yet — fail safe rather than fail loud

    vectorizer, model = loaded
    try:
        vec = vectorizer.transform([text])
        label = model.predict(vec)[0]
        return label if label in OUR_LABELS else "neutral"
    except Exception:
        return "neutral"
