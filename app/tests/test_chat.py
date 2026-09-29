import json

import openai
import pytest

from conftest import make_companion, make_conversation, run_jobs, user_by_email
from conversation.context import build_context
from core.config import settings
from models import Conversation, Job, Message


def _events(res) -> list[dict]:
    return [json.loads(line) for line in res.text.splitlines() if line.strip()]


@pytest.fixture
def setup(make_client, db):
    client = make_client("a@example.com")
    user = user_by_email(db, "a@example.com")
    conversation = make_conversation(db, user, make_companion(db, user))
    return client, user, conversation


def test_chat_streams_ndjson_and_saves_completed_reply(setup, fake_llm, db):
    client, _user, conversation = setup
    res = client.post("/api/chat", json={"conversation_id": conversation.id, "message": "Hi there, how are you today?"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/x-ndjson")
    events = _events(res)
    assert events[0]["type"] == "start"
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Hello there!"
    assert events[-1] == {"type": "done", "status": "completed", "message_id": events[0]["message_id"]}

    db.expire_all()
    reply = db.get(Message, events[0]["message_id"])
    assert (reply.status, reply.content, reply.role) == ("completed", "Hello there!", "assistant")
    assert db.get(Conversation, conversation.id).title.startswith("Hi there")


def test_llm_failure_before_first_token_returns_error_and_marks_failed(setup, fake_llm, db):
    client, _user, conversation = setup
    fake_llm.error = openai.APIConnectionError(request=None)
    res = client.post("/api/chat", json={"conversation_id": conversation.id, "message": "hello"})
    assert res.status_code == 502
    error = res.json()["error"]
    assert error["code"] == "LLM_UNAVAILABLE"
    db.expire_all()
    failed = db.get(Message, error["message_id"])
    assert failed.status == "failed" and failed.error_code == "LLM_UNAVAILABLE" and failed.content == ""


def test_llm_failure_mid_stream_keeps_partial_text(setup, fake_llm, db):
    client, _user, conversation = setup
    fake_llm.replies = ["Partial ", openai.APIConnectionError(request=None)]
    events = _events(client.post("/api/chat", json={"conversation_id": conversation.id, "message": "hello"}))
    assert events[-1]["type"] == "error" and events[-1]["code"] == "LLM_UNAVAILABLE"
    db.expire_all()
    message = db.get(Message, events[0]["message_id"])
    assert message.status == "failed" and message.content == "Partial"


def test_fallback_model_used_when_primary_fails(setup, fake_llm, db, monkeypatch):
    client, _user, conversation = setup
    import dataclasses

    import llm.openrouter as llm

    monkeypatch.setattr(llm, "settings", dataclasses.replace(settings, openrouter_fallback_models=["backup/model"]))
    original_create = fake_llm.create

    def create(**kwargs):
        if kwargs["model"] != "backup/model":
            raise openai.NotFoundError("no such model", response=_response(404), body=None)
        return original_create(**kwargs)

    fake_llm.create = create
    events = _events(client.post("/api/chat", json={"conversation_id": conversation.id, "message": "hello"}))
    assert events[0]["model"] == "backup/model"
    assert events[-1]["status"] == "completed"


def _response(status):
    import httpx

    return httpx.Response(status, request=httpx.Request("POST", "https://openrouter.test"))


def test_regenerate_replaces_last_reply(setup, fake_llm, db):
    client, _user, conversation = setup
    first = _events(client.post("/api/chat", json={"conversation_id": conversation.id, "message": "hello"}))
    fake_llm.replies = ["A different answer"]
    second = _events(client.post("/api/chat/regenerate", json={"conversation_id": conversation.id}))
    assert second[-1]["status"] == "completed"
    db.expire_all()
    assert db.query(Message).filter(Message.id == first[0]["message_id"]).count() == 0
    assistants = db.query(Message).filter(Message.conversation_id == conversation.id, Message.role == "assistant").all()
    assert [m.content for m in assistants] == ["A different answer"]


def test_retry_after_failure(setup, fake_llm, db):
    client, _user, conversation = setup
    fake_llm.error = openai.APITimeoutError(request=None)
    assert client.post("/api/chat", json={"conversation_id": conversation.id, "message": "hello"}).status_code == 502
    fake_llm.error = None
    events = _events(client.post("/api/chat/regenerate", json={"conversation_id": conversation.id}))
    assert events[-1]["status"] == "completed"
    db.expire_all()
    statuses = [m.status for m in db.query(Message).filter(Message.conversation_id == conversation.id).order_by(Message.created_at)]
    assert statuses == ["completed", "completed"]  # the failed reply was replaced, not kept


def test_cancel_endpoint_marks_orphaned_reply_cancelled(setup, db):
    client, _user, conversation = setup
    stuck = Message(conversation_id=conversation.id, role="assistant", content="", status="streaming")
    db.add(stuck)
    db.commit()
    assert client.post(f"/api/messages/{stuck.id}/cancel").json()["status"] == "cancelled"


def test_message_length_limit(setup, fake_llm):
    client, _user, conversation = setup
    res = client.post(
        "/api/chat", json={"conversation_id": conversation.id, "message": "x" * (settings.max_message_chars + 1)}
    )
    assert res.status_code == 422


def test_context_is_bounded_and_skips_failed_messages(db, make_client):
    make_client("a@example.com")
    user = user_by_email(db, "a@example.com")
    conversation = make_conversation(
        db, user, make_companion(db, user), [("user" if i % 2 == 0 else "assistant", f"message {i}") for i in range(60)]
    )
    db.add(Message(conversation_id=conversation.id, role="assistant", content="", status="failed"))
    db.commit()
    built = build_context(
        db,
        conversation,
        persona_prompt="You are Nova.",
        emotion_context=None,
        language_instruction="Reply in English.",
        memory_enabled=False,
        query_text="hello",
    )
    history = built.messages[1:]
    assert len(history) <= settings.context_recent_messages
    assert history[-1]["content"] == "message 59"  # newest kept
    assert all(m["content"] for m in history)  # failed/empty rows never replayed
    assert built.messages[0]["role"] == "system" and "You are Nova." in built.messages[0]["content"]


def test_long_conversation_gets_summarized(setup, fake_llm, db):
    client, user, conversation = setup
    for i in range(settings.summary_trigger_messages + 2):
        db.add(Message(conversation_id=conversation.id, role="user" if i % 2 == 0 else "assistant", content=f"m{i}"))
        db.flush()
    db.commit()

    _events(client.post("/api/chat", json={"conversation_id": conversation.id, "message": "hello"}))
    assert db.query(Job).filter(Job.kind == "summarize_conversation").count() == 1

    fake_llm.completion_text = "The user said many things."
    run_jobs()
    db.expire_all()
    refreshed = db.get(Conversation, conversation.id)
    assert refreshed.summary == "The user said many things."
    assert refreshed.summarized_until is not None
    # the summary is now part of the next prompt, and summarized messages are not
    built = build_context(
        db, refreshed, persona_prompt="p", emotion_context=None, language_instruction="l", memory_enabled=False, query_text="x"
    )
    assert "The user said many things." in built.messages[0]["content"]
    assert all(m["content"] != "m0" for m in built.messages[1:])


def test_chat_rate_limited(setup, fake_llm, monkeypatch):
    client, _user, conversation = setup
    import dataclasses

    import core.rate_limit as rl

    monkeypatch.setattr(rl, "settings", dataclasses.replace(settings, rate_limits={**settings.rate_limits, "chat": "2/minute"}))
    codes = [client.post("/api/chat", json={"conversation_id": conversation.id, "message": "hi"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
