"""
User emotion detection. Primary signal is the locally trained TF-IDF + logistic
regression model (see train_classifier.py); keyword rules are only a fallback for when
the model is missing or unsure, and for "stressed", which has no training examples.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib

from emotion.label_mapping import OUR_LABELS

MODEL_PATH = Path(__file__).resolve().parent.parent / "models_store" / "emotion_classifier.joblib"

# below this the model's top guess is treated as "not sure" and keywords may override it
LOW_CONFIDENCE = 0.45

# "stressed" has zero training examples in either source dataset (neither GoEmotions
# nor the EmpatheticDialogues set uses that exact label), so it is only reachable here.
KEYWORD_RULES: list[tuple[str, re.Pattern]] = [
    (
        "stressed",
        re.compile(
            r"\b(stress(ed|ful)?|overwhelm(ed|ing)?|deadlines?|burn(ed|t)? out|too much (going on|to do)|swamped)\b",
            re.IGNORECASE,
        ),
    ),
    ("anxious", re.compile(r"\b(anxious|anxiety|panic(king)?|can'?t stop worrying)\b", re.IGNORECASE)),
    ("lonely", re.compile(r"\b(lonely|alone|no one to talk to|isolated)\b", re.IGNORECASE)),
    ("angry", re.compile(r"\b(furious|so angry|pissed off|hate (this|it|you))\b", re.IGNORECASE)),
    ("sad", re.compile(r"\b(sad|depressed|heartbroken|miserable|crying)\b", re.IGNORECASE)),
]
KEYWORD_CONFIDENCE = 0.6


@dataclass(frozen=True)
class EmotionResult:
    emotion: str
    confidence: float
    source: str  # "model" | "keyword" | "default"

    def as_dict(self) -> dict:
        return {"emotion": self.emotion, "confidence": round(self.confidence, 2)}


NEUTRAL = EmotionResult("neutral", 0.0, "default")


@lru_cache(maxsize=1)
def _load():
    if not MODEL_PATH.exists():
        return None
    artifact = joblib.load(MODEL_PATH)
    return artifact["vectorizer"], artifact["model"]


def model_available() -> bool:
    return _load() is not None


def _keyword_match(text: str) -> EmotionResult | None:
    for label, pattern in KEYWORD_RULES:
        if pattern.search(text):
            return EmotionResult(label, KEYWORD_CONFIDENCE, "keyword")
    return None


def _model_predict(text: str) -> EmotionResult | None:
    loaded = _load()
    if loaded is None:
        return None
    vectorizer, model = loaded
    try:
        vec = vectorizer.transform([text])
        if hasattr(model, "predict_proba"):
            probabilities = model.predict_proba(vec)[0]
            best = int(probabilities.argmax())
            label, confidence = model.classes_[best], float(probabilities[best])
        else:
            label, confidence = model.predict(vec)[0], 0.5
    except Exception:
        return None
    if label not in OUR_LABELS:
        return None
    return EmotionResult(label, confidence, "model")


def detect_emotion(text: str) -> EmotionResult:
    text = (text or "").strip()
    if not text:
        return NEUTRAL

    predicted = _model_predict(text)
    keyword = _keyword_match(text)

    if predicted is None:
        return keyword or NEUTRAL
    # keywords win only when the model is unsure, or (for keyword-only "stressed") when the
    # model saw nothing emotional at all
    if keyword and (
        predicted.confidence < LOW_CONFIDENCE
        or (keyword.emotion == "stressed" and predicted.emotion in ("neutral", "calm"))
    ):
        return keyword
    return predicted


def classify_emotion(text: str) -> str:
    """Label-only helper kept for existing callers."""
    return detect_emotion(text).emotion
