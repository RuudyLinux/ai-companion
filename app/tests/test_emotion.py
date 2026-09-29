import numpy as np
import pytest

import emotion.classifier as classifier
from emotion.classifier import EmotionResult, detect_emotion
from emotion.strategy import strategy_for
from voice.adaptive import resolve_adaptive_effect


class FakeModel:
    def __init__(self, probabilities: dict[str, float]):
        self.classes_ = np.array(list(probabilities))
        self._p = np.array([list(probabilities.values())])

    def predict_proba(self, _vec):
        return self._p


class FakeVectorizer:
    def transform(self, texts):
        return texts


def _use_model(monkeypatch, probabilities):
    monkeypatch.setattr(classifier, "_load", lambda: (FakeVectorizer(), FakeModel(probabilities)))


def test_returns_emotion_and_confidence(monkeypatch):
    _use_model(monkeypatch, {"sad": 0.87, "neutral": 0.13})
    result = detect_emotion("I lost my dog today")
    assert result == EmotionResult("sad", pytest.approx(0.87), "model")
    assert result.as_dict() == {"emotion": "sad", "confidence": 0.87}


def test_keyword_fallback_when_model_missing(monkeypatch):
    monkeypatch.setattr(classifier, "_load", lambda: None)
    assert detect_emotion("I'm so stressed about this deadline").emotion == "stressed"
    assert detect_emotion("the weather is fine").emotion == "neutral"


def test_confident_model_beats_keywords(monkeypatch):
    _use_model(monkeypatch, {"sad": 0.9, "neutral": 0.1})
    assert detect_emotion("the deadline made me cry, I miss her").emotion == "sad"


def test_stressed_keyword_overrides_neutral_prediction(monkeypatch):
    _use_model(monkeypatch, {"neutral": 0.8, "sad": 0.2})
    result = detect_emotion("work is overwhelming right now")
    assert (result.emotion, result.source) == ("stressed", "keyword")


def test_low_confidence_prediction_yields_to_keyword(monkeypatch):
    _use_model(monkeypatch, {"happy": 0.3, "sad": 0.25, "neutral": 0.45 - 0.01})
    assert detect_emotion("I feel so lonely lately").emotion == "lonely"


def test_empty_text_is_neutral():
    assert detect_emotion("   ").emotion == "neutral"


def test_strategy_does_not_mirror_anger():
    strategy = strategy_for(EmotionResult("angry", 0.9, "model"))
    assert strategy.name == "de-escalate"
    assert strategy.voice_preset == "calm"
    assert "calm" in strategy.tone


def test_uncertain_emotion_uses_neutral_strategy():
    assert strategy_for(EmotionResult("angry", 0.1, "model")).name == "inform"


def test_adaptive_voice_follows_strategy_not_user_emotion(monkeypatch):
    monkeypatch.setattr(classifier, "_load", lambda: None)
    preset = resolve_adaptive_effect(
        assistant_reply_text="I hear you, let's work through this together.",
        user_emotion="angry",
        persona_prompt="A friend",
        formal_casual="casual",
    )
    assert preset == "calm"


def test_emotion_recorded_only_when_tracking_enabled(make_client, db, fake_llm, monkeypatch):
    from conftest import make_companion, make_conversation, user_by_email
    from models import EmotionalMemory, Message

    monkeypatch.setattr(classifier, "_load", lambda: None)
    client = make_client("a@example.com")
    user = user_by_email(db, "a@example.com")
    conversation = make_conversation(db, user, make_companion(db, user))

    client.post("/api/chat", json={"conversation_id": conversation.id, "message": "I am so stressed about my exams"})
    db.expire_all()
    message = db.query(Message).filter(Message.role == "user").one()
    assert (message.emotion, message.response_strategy) == ("stressed", "reassure")
    assert "Response strategy: reassure" in fake_llm.requests[-1]["messages"][0]["content"]

    client.post("/settings/emotion-toggle", data={"enabled": "false"})
    client.post("/api/chat", json={"conversation_id": conversation.id, "message": "still stressed honestly"})
    db.expire_all()
    latest = db.query(Message).filter(Message.role == "user").order_by(Message.created_at.desc()).first()
    assert latest.emotion is None
    assert len(db.get(EmotionalMemory, user.id).recent_emotions) == 1
