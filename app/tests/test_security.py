from conftest import make_companion, make_conversation, make_voice, user_by_email


def test_post_without_csrf_token_is_rejected(make_client, db):
    client = make_client("a@example.com")
    res = client.request("POST", "/companions/new", data={"name": "X", "description": "Y"}, csrf=False, follow_redirects=False)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "CSRF_FAILED"


def test_post_with_wrong_csrf_token_is_rejected(make_client):
    client = make_client("a@example.com")
    res = client.request("DELETE", "/api/me/memories", headers={"X-CSRF-Token": "forged.token"})
    assert res.status_code == 403


def test_login_form_requires_csrf(client, db):
    res = client.request("POST", "/login", data={"email": "a@example.com", "password": "x"}, csrf=False)
    assert res.status_code == 403


def test_csrf_form_field_accepted(client):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    res = client.request(
        "POST", "/login", data={"email": "a@example.com", "password": "x", "csrf_token": token}, csrf=False,
        follow_redirects=False,
    )
    assert res.status_code == 303  # reached the handler (bad credentials redirect), not blocked


def test_user_cannot_access_other_users_conversation(make_client, db):
    make_client("a@example.com")
    client_b = make_client("b@example.com")
    a = user_by_email(db, "a@example.com")
    conversation = make_conversation(db, a, make_companion(db, a), [("user", "secret diary")])

    assert client_b.get(f"/chat/conversation/{conversation.id}").status_code == 404
    assert client_b.get(f"/api/conversations/{conversation.id}/export").status_code == 404
    assert client_b.post(f"/api/conversations/{conversation.id}/rename", json={"title": "pwned"}).status_code == 404
    assert client_b.delete(f"/api/conversations/{conversation.id}").status_code == 404
    res = client_b.post("/api/chat", json={"conversation_id": conversation.id, "message": "hi"})
    assert res.status_code == 404 and res.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert client_b.get("/api/search", params={"q": "secret"}).json() == []


def test_user_cannot_access_other_users_messages(make_client, db, fake_engine):
    make_client("a@example.com")
    client_b = make_client("b@example.com")
    a = user_by_email(db, "a@example.com")
    conversation = make_conversation(db, a, make_companion(db, a), [("user", "hi"), ("assistant", "hello")])
    assistant_id = conversation.messages[-1].id
    voice = make_voice(db)

    res = client_b.post(f"/api/messages/{assistant_id}/speak", json={"voice_id": voice.id})
    assert res.status_code == 404 and res.json()["error"]["code"] == "MESSAGE_NOT_FOUND"
    assert client_b.post(f"/api/messages/{assistant_id}/cancel").status_code == 404


def test_private_companion_hidden_from_other_users(make_client, db):
    make_client("a@example.com")
    client_b = make_client("b@example.com")
    a = user_by_email(db, "a@example.com")
    private = make_companion(db, a, "Secret", public=False)
    public = make_companion(db, a, "Open", public=True)

    assert client_b.get(f"/chat/{private.id}").status_code == 404
    assert client_b.post(f"/chat/{private.id}/new", follow_redirects=False).status_code == 404
    assert client_b.get(f"/chat/{public.id}").status_code == 200
    listing = client_b.get("/companions").text
    assert "Open" in listing and "Secret" not in listing


def test_error_responses_do_not_leak_internals(make_client, db, monkeypatch):
    client = make_client("a@example.com")
    import routers.conversations as conversations

    def boom(*args, **kwargs):
        raise RuntimeError("password=hunter2 at C:\\internal\\path.py")

    monkeypatch.setattr(conversations, "_conversation_summary", boom)
    a = user_by_email(db, "a@example.com")
    make_conversation(db, a, make_companion(db, a))
    safe_client = type(client)(client.app, raise_server_exceptions=False)
    safe_client.cookies = client.cookies
    res = safe_client.get("/api/conversations")
    assert res.status_code == 500
    body = res.text
    assert "hunter2" not in body and "path.py" not in body and "Traceback" not in body
    assert res.json()["error"]["code"] == "INTERNAL_ERROR"


def test_validation_errors_use_standard_shape(make_client):
    client = make_client("a@example.com")
    res = client.post("/api/chat", json={"conversation_id": "not-a-uuid", "message": ""})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_security_headers_and_request_id(client):
    res = client.get("/health/live", headers={"X-Request-ID": "abc-123"})
    assert res.headers["x-request-id"] == "abc-123"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    generated = client.get("/health/live", headers={"X-Request-ID": "bad id with spaces"}).headers["x-request-id"]
    assert generated != "bad id with spaces" and len(generated) == 32


def test_oversized_request_body_rejected_before_parsing(make_client):
    client = make_client("a@example.com")
    res = client.post("/api/stt", files={"audio": ("big.wav", b"\0" * (3 * 1024 * 1024), "audio/wav")})
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
