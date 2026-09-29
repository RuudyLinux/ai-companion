import json
from datetime import timedelta

from conftest import PASSWORD, make_companion, make_conversation, run_jobs, user_by_email
from memory.extraction import upsert_memory, worth_extracting
from memory.retrieval import retrieve_memories
from models import Conversation, Job, Memory, User, now


def _chat(client, conversation_id, text):
    return client.post("/api/chat", json={"conversation_id": conversation_id, "message": text})


def _setup(make_client, db):
    client = make_client("a@example.com")
    user = user_by_email(db, "a@example.com")
    return client, user, make_conversation(db, user, make_companion(db, user))


def test_prefilter_only_queues_self_disclosure():
    assert worth_extracting("My sister Priya is visiting next week")
    assert worth_extracting("I love hiking in the mountains")
    assert not worth_extracting("what's the weather?")
    assert not worth_extracting("ok")


def test_extraction_stores_valid_memories_and_drops_secrets(make_client, db, fake_llm):
    client, user, conversation = _setup(make_client, db)
    fake_llm.completion_text = json.dumps(
        [
            {"type": "relationship", "content": "User's sister is named Priya", "importance": 0.8, "confidence": 0.9},
            {"type": "event", "content": "User has an exam next week", "importance": 0.6, "confidence": 0.9, "ttl_days": 14},
            {"type": "fact", "content": "User's password is hunter2", "importance": 0.9, "confidence": 0.99},
            {"type": "fact", "content": "User might like jazz", "importance": 0.3, "confidence": 0.2},
            {"type": "made_up", "content": "whatever", "importance": 1, "confidence": 1},
        ]
    )
    _chat(client, conversation.id, "My sister Priya says hi, and I have an exam next week")
    assert db.query(Job).filter(Job.kind == "extract_memories").count() == 1
    run_jobs()

    memories = {m.content: m for m in db.query(Memory).filter(Memory.user_id == user.id)}
    assert set(memories) == {"User's sister is named Priya", "User has an exam next week"}
    assert memories["User has an exam next week"].expires_at is not None
    assert memories["User's sister is named Priya"].source_message_id is not None


def test_small_talk_does_not_trigger_extraction(make_client, db, fake_llm):
    client, _user, conversation = _setup(make_client, db)
    _chat(client, conversation.id, "what time is it?")
    assert db.query(Job).filter(Job.kind == "extract_memories").count() == 0


def test_similar_memories_are_merged(db, make_client):
    _client, user, _conversation = _setup(make_client, db)
    base = {"type": "fact", "importance": 0.5, "confidence": 0.8, "ttl_days": None}
    upsert_memory(db, user.id, None, {**base, "content": "User loves hiking"}, None)
    db.commit()
    upsert_memory(db, user.id, None, {**base, "content": "User loves hiking in the mountains", "importance": 0.7}, None)
    upsert_memory(db, user.id, None, {**base, "content": "User works as a nurse"}, None)
    db.commit()
    rows = {m.content: m for m in db.query(Memory).filter(Memory.user_id == user.id)}
    assert set(rows) == {"User loves hiking in the mountains", "User works as a nurse"}
    assert rows["User loves hiking in the mountains"].importance == 0.7


def test_memory_disabled_means_no_extraction_and_no_retrieval(make_client, db, fake_llm):
    client, user, conversation = _setup(make_client, db)
    db.add(Memory(user_id=user.id, type="profile", content="User's name is Asha", importance=0.9, confidence=1))
    db.commit()
    client.post("/settings/privacy", data={"store_voice_audio": "true"})  # memory_enabled unchecked
    db.expire_all()
    assert db.get(User, user.id).memory_enabled is False

    _chat(client, conversation.id, "My favourite colour is green")
    assert db.query(Job).filter(Job.kind == "extract_memories").count() == 0
    assert "Asha" not in fake_llm.requests[-1]["messages"][0]["content"]


def test_relevant_memories_reach_the_prompt(make_client, db, fake_llm):
    client, user, conversation = _setup(make_client, db)
    db.add_all(
        [
            Memory(user_id=user.id, type="profile", content="User's name is Asha", importance=0.9, confidence=1),
            Memory(user_id=user.id, type="interest", content="User plays chess on weekends", importance=0.4, confidence=0.9),
            Memory(
                user_id=user.id,
                type="event",
                content="User had a dentist appointment",
                importance=0.4,
                confidence=0.9,
                expires_at=now() - timedelta(days=1),
            ),
        ]
    )
    db.commit()
    _chat(client, conversation.id, "any chess openings you'd recommend?")
    system_prompt = fake_llm.requests[-1]["messages"][0]["content"]
    assert "User's name is Asha" in system_prompt  # profile always included
    assert "chess on weekends" in system_prompt  # relevant
    assert "dentist" not in system_prompt  # expired


def test_retrieval_respects_companion_scope(make_client, db):
    _client, user, conversation = _setup(make_client, db)
    other_companion = make_companion(db, user, "Other")
    db.add(
        Memory(user_id=user.id, companion_id=other_companion.id, type="relationship", content="calls Other 'buddy'",
               importance=0.9, confidence=1)
    )
    db.commit()
    assert retrieve_memories(db, user.id, conversation.companion_id, "buddy") == []


def test_memory_management_endpoints(make_client, db):
    client, user, _conversation = _setup(make_client, db)
    other = make_client("b@example.com")
    memory = Memory(user_id=user.id, type="fact", content="User is vegetarian", importance=0.5, confidence=0.8)
    db.add(memory)
    db.commit()

    assert [m["content"] for m in client.get("/api/me/memories").json()] == ["User is vegetarian"]
    assert other.get("/api/me/memories").json() == []
    assert other.delete(f"/api/me/memories/{memory.id}").status_code == 404
    edited = client.patch(f"/api/me/memories/{memory.id}", json={"content": "User is vegan"}).json()
    assert edited["content"] == "User is vegan" and edited["confidence"] == 1.0
    assert client.delete("/api/me/memories").json()["deleted"] == 1
    assert client.get("/api/me/memories").json() == []


def test_export_contains_user_data_only(make_client, db):
    client, user, conversation = _setup(make_client, db)
    make_client("b@example.com")
    db.add(Memory(user_id=user.id, type="fact", content="User is vegetarian", importance=0.5, confidence=0.8))
    db.commit()
    data = client.get("/api/me/export").json()
    assert data["account"]["email"] == "a@example.com"
    assert "hashed_password" not in json.dumps(data)
    assert [c["id"] for c in data["conversations"]] == [conversation.id]
    assert data["memories"][0]["content"] == "User is vegetarian"


def test_delete_account_removes_everything(make_client, db):
    client, user, conversation = _setup(make_client, db)
    user_id, conversation_id = user.id, conversation.id
    db.add(Memory(user_id=user.id, type="fact", content="x", importance=0.5, confidence=0.8))
    db.commit()
    bad = client.post("/settings/delete-account", data={"password": "wrong-one", "confirm": "DELETE"}, follow_redirects=False)
    assert bad.headers["location"] == "/settings?notice=invalid_password"

    res = client.post("/settings/delete-account", data={"password": PASSWORD, "confirm": "DELETE"}, follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"].startswith("/login")
    db.expire_all()
    assert db.query(User).filter(User.id == user_id).count() == 0
    assert db.query(Memory).count() == 0
    assert db.query(Conversation).filter(Conversation.id == conversation_id).count() == 0
    assert client.get("/api/conversations").status_code == 401


def test_retention_sweep_deletes_old_conversations(make_client, db):
    from privacy.service import run_retention

    _client, user, conversation = _setup(make_client, db)
    user.data_retention_days = 30
    db.query(Conversation).filter(Conversation.id == conversation.id).update(
        {Conversation.updated_at: now() - timedelta(days=31)}, synchronize_session=False
    )
    db.commit()
    assert run_retention(db)["conversations"] == 1
    assert db.query(Conversation).filter(Conversation.id == conversation.id).count() == 0
