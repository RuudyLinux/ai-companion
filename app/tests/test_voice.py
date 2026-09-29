from conftest import (
    FakeEngine,
    make_companion,
    make_conversation,
    make_voice,
    run_jobs,
    user_by_email,
    wav_bytes,
)
from core import storage
from models import Job, User, Voice, VoiceMessage


def _reply(db, email):
    user = user_by_email(db, email)
    conversation = make_conversation(db, user, make_companion(db, user), [("user", "hi"), ("assistant", "Hello friend")])
    return user, conversation.messages[-1]


def test_speak_queues_job_then_serves_audio(make_client, db, fake_engine):
    client = make_client("a@example.com")
    _user, reply = _reply(db, "a@example.com")
    voice = make_voice(db)

    res = client.post(f"/api/messages/{reply.id}/speak", json={"voice_id": voice.id, "tts_effect": "calm"})
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "queued"

    assert run_jobs() == 1
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "completed"
    audio = client.get(job["result"]["audio_url"])
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"
    assert fake_engine.calls[0]["speaker_name"] == "Ana"

    # same voice + effect again: served from cache, no new job
    again = client.post(f"/api/messages/{reply.id}/speak", json={"voice_id": voice.id, "tts_effect": "calm"})
    assert again.status_code == 200 and again.json()["status"] == "completed"


def test_stored_audio_path_is_relative(make_client, db, fake_engine):
    client = make_client("a@example.com")
    _user, reply = _reply(db, "a@example.com")
    client.post(f"/api/messages/{reply.id}/speak", json={"voice_id": make_voice(db).id})
    run_jobs()
    db.expire_all()
    vm = db.query(VoiceMessage).one()
    assert vm.audio_path.startswith("voice_audio/")
    assert "voice_audio" not in client.get("/api/voice-messages").text.replace("/media/voice", "")


def test_user_cannot_use_another_users_cloned_voice(make_client, db, fake_engine):
    make_client("a@example.com")
    client_b = make_client("b@example.com")
    a = user_by_email(db, "a@example.com")
    cloned = make_voice(db, owner=a, name="A's voice")
    _b, reply = _reply(db, "b@example.com")

    res = client_b.post(f"/api/messages/{reply.id}/speak", json={"voice_id": cloned.id})
    assert res.status_code == 404 and res.json()["error"]["code"] == "VOICE_NOT_FOUND"
    assert client_b.post(f"/api/voices/{cloned.id}/preview").status_code == 404
    assert client_b.get(f"/api/voices/{cloned.id}/preview").status_code == 404
    assert client_b.delete(f"/api/voices/{cloned.id}").status_code == 404
    assert cloned.id not in client_b.get("/voices").text
    assert all(v["id"] != cloned.id for v in client_b.get("/api/voices").json())


def test_user_cannot_set_foreign_voice_as_default(make_client, db):
    make_client("a@example.com")
    client_b = make_client("b@example.com")
    cloned = make_voice(db, owner=user_by_email(db, "a@example.com"))
    res = client_b.post("/settings/voice-preferences", data={"default_voice_id": cloned.id})
    assert res.status_code == 404
    db.expire_all()
    assert user_by_email(db, "b@example.com").default_voice_id is None


def test_user_cannot_fetch_another_users_audio(make_client, db, fake_engine):
    client_a = make_client("a@example.com")
    client_b = make_client("b@example.com")
    _a, reply = _reply(db, "a@example.com")
    job_id = client_a.post(f"/api/messages/{reply.id}/speak", json={"voice_id": make_voice(db).id}).json()["job_id"]
    run_jobs()
    audio_url = client_a.get(f"/api/jobs/{job_id}").json()["result"]["audio_url"]

    assert client_b.get(audio_url).status_code == 404
    assert client_b.get(f"/api/jobs/{job_id}").status_code == 404
    vm_id = audio_url.rsplit("/", 1)[1]
    assert client_b.delete(f"/api/voice-messages/{vm_id}").status_code == 404


def test_invalid_voice_and_effect_rejected(make_client, db, fake_engine):
    client = make_client("a@example.com")
    _user, reply = _reply(db, "a@example.com")
    res = client.post(f"/api/messages/{reply.id}/speak", json={"voice_id": "00000000-0000-0000-0000-000000000000"})
    assert res.status_code == 404
    res = client.post(f"/api/messages/{reply.id}/speak", json={"voice_id": "nope"})
    assert res.status_code == 422
    res = client.post(f"/api/messages/{reply.id}/speak", json={"voice_id": make_voice(db).id, "tts_effect": "rm -rf"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "INVALID_EFFECT"


def test_tts_failure_is_reported_without_internal_details(make_client, db, monkeypatch):
    client = make_client("a@example.com")
    _user, reply = _reply(db, "a@example.com")
    import routers.speech
    import voice.service

    failing = FakeEngine(fail=True)
    monkeypatch.setattr(voice.service, "get_engine", lambda: failing)
    monkeypatch.setattr(routers.speech, "get_engine", lambda: failing)
    job_id = client.post(f"/api/messages/{reply.id}/speak", json={"voice_id": make_voice(db).id}).json()["job_id"]
    run_jobs()
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "TTS_FAILED"
    assert "secret" not in job["error"]["message"] and "CUDA" not in job["error"]["message"]


def test_unsupported_language_skips_audio(make_client, db, fake_engine):
    client = make_client("a@example.com")
    _user, reply = _reply(db, "a@example.com")
    reply.language = "ta"
    db.commit()
    res = client.post(f"/api/messages/{reply.id}/speak", json={"voice_id": make_voice(db).id})
    assert res.json()["skipped"] is True
    assert db.query(Job).count() == 0


def test_cancel_queued_tts_job(make_client, db, fake_engine):
    client = make_client("a@example.com")
    _user, reply = _reply(db, "a@example.com")
    job_id = client.post(f"/api/messages/{reply.id}/speak", json={"voice_id": make_voice(db).id}).json()["job_id"]
    assert client.post(f"/api/jobs/{job_id}/cancel").json()["status"] == "cancelled"
    assert run_jobs() == 0
    assert fake_engine.calls == []


def test_clone_voice_flow(make_client, db, fake_engine):
    client = make_client("a@example.com")
    other = make_client("b@example.com")

    res = client.post(
        "/api/voices/clone",
        data={"name": "My voice", "language": "English", "consent": "true"},
        files={"audio": ("me.wav", wav_bytes(4.0), "audio/wav")},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert set(body) == {"id", "name", "category", "kind", "language", "owned"}  # no paths leak

    voice = db.get(Voice, body["id"])
    reference = storage.resolve(voice.clone_reference)
    assert voice.owner_id == user_by_email(db, "a@example.com").id and reference.exists()
    assert voice.consent_confirmed_at is not None
    assert body["id"] not in [v["id"] for v in other.get("/api/voices").json()]

    # the cloned voice is synthesized from its stored reference file
    _user, reply = _reply(db, "a@example.com")
    client.post(f"/api/messages/{reply.id}/speak", json={"voice_id": voice.id})
    run_jobs()
    assert fake_engine.calls[-1]["speaker_wav"] == str(reference)

    assert client.delete(f"/api/voices/{voice.id}").json() == {"ok": True}
    assert not reference.exists()
    assert db.query(VoiceMessage).count() == 0


def test_clone_requires_consent_and_real_audio(make_client, db):
    client = make_client("a@example.com")
    no_consent = client.post(
        "/api/voices/clone",
        data={"name": "x", "consent": "false"},
        files={"audio": ("me.wav", wav_bytes(4.0), "audio/wav")},
    )
    assert no_consent.status_code == 422 and no_consent.json()["error"]["code"] == "CONSENT_REQUIRED"

    fake = client.post(
        "/api/voices/clone",
        data={"name": "x", "consent": "true"},
        files={"audio": ("me.wav", b"RIFF\x00\x00\x00\x00WAVEgarbage", "audio/wav")},
    )
    assert fake.status_code == 422 and fake.json()["error"]["code"] == "INVALID_AUDIO"

    too_short = client.post(
        "/api/voices/clone",
        data={"name": "x", "consent": "true"},
        files={"audio": ("me.wav", wav_bytes(1.0), "audio/wav")},
    )
    assert too_short.status_code == 422 and too_short.json()["error"]["code"] == "AUDIO_TOO_SHORT"
    assert db.query(Voice).count() == 0
    assert not any(storage.settings.voice_refs_dir.iterdir())


def test_builtin_voice_visible_to_all_but_not_deletable(make_client, db):
    client = make_client("a@example.com")
    builtin = make_voice(db)
    assert builtin.id in [v["id"] for v in client.get("/api/voices").json()]
    assert client.delete(f"/api/voices/{builtin.id}").status_code == 404


def test_voices_of_inactive_engine_hidden(make_client, db):
    client = make_client("a@example.com")
    db.add(Voice(name="Cloud", category="x", kind="builtin", provider="inworld", provider_voice_id="cloud-1"))
    db.commit()
    assert client.get("/api/voices").json() == []
    assert db.query(User).count() == 1
