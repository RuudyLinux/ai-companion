from conftest import make_companion, make_conversation, make_voice, user_by_email
from core import storage
from core.config import settings
from models import Message, VoiceMessage


def test_list_rename_pin_archive(make_client, db):
    client = make_client("a@example.com")
    user = user_by_email(db, "a@example.com")
    conversation = make_conversation(db, user, make_companion(db, user))

    assert [c["id"] for c in client.get("/api/conversations").json()] == [conversation.id]
    assert client.post(f"/api/conversations/{conversation.id}/rename", json={"title": "  Trip  "}).json()["title"] == "Trip"
    assert client.post(f"/api/conversations/{conversation.id}/pin", json={"value": True}).json()["pinned"] is True
    client.post(f"/api/conversations/{conversation.id}/archive", json={"value": True})
    assert client.get("/api/conversations").json() == []
    assert len(client.get("/api/conversations", params={"archived": True}).json()) == 1


def test_rename_validation(make_client, db):
    client = make_client("a@example.com")
    user = user_by_email(db, "a@example.com")
    conversation = make_conversation(db, user, make_companion(db, user))
    assert client.post(f"/api/conversations/{conversation.id}/rename", json={"title": "   "}).status_code == 422
    assert client.post(f"/api/conversations/{conversation.id}/rename", json={"title": "x" * 121}).status_code == 422


def test_delete_removes_messages_voice_rows_and_audio_files(make_client, db):
    client = make_client("a@example.com")
    user = user_by_email(db, "a@example.com")
    conversation = make_conversation(db, user, make_companion(db, user), [("user", "hi"), ("assistant", "hello")])
    assistant = conversation.messages[-1]
    audio = settings.voice_audio_dir / f"{assistant.id}.wav"
    audio.write_bytes(b"RIFF....WAVE")
    db.add(VoiceMessage(message_id=assistant.id, audio_path=storage.to_key(audio), voice_id=make_voice(db).id))
    db.commit()

    assert client.delete(f"/api/conversations/{conversation.id}").json() == {"ok": True}
    db.expire_all()
    assert db.query(Message).count() == 0
    assert db.query(VoiceMessage).count() == 0
    assert not audio.exists()


def test_search_escapes_like_wildcards(make_client, db):
    client = make_client("a@example.com")
    user = user_by_email(db, "a@example.com")
    make_conversation(db, user, make_companion(db, user), [("user", "100% sure"), ("user", "totally unrelated")])
    results = client.get("/api/search", params={"q": "%"}).json()
    assert [r["snippet"] for r in results] == ["100% sure"]


def test_export_conversation_text(make_client, db):
    client = make_client("a@example.com")
    user = user_by_email(db, "a@example.com")
    conversation = make_conversation(db, user, make_companion(db, user), [("user", "hi"), ("assistant", "hello")])
    res = client.get(f"/api/conversations/{conversation.id}/export")
    assert res.status_code == 200 and "You: hi" in res.text and "Nova: hello" in res.text
