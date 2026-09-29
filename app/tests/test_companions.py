from conftest import make_companion, user_by_email
from models import Companion


def test_create_companion(make_client, db):
    client = make_client("a@example.com")
    res = client.post("/companions/new", data={"name": "Nova", "description": "A kind friend."}, follow_redirects=False)
    assert res.status_code == 303
    companion = db.query(Companion).one()
    assert res.headers["location"] == f"/chat/{companion.id}"
    assert companion.is_public is False
    assert "A kind friend." in companion.persona_prompt


def test_create_companion_validation(make_client, db):
    client = make_client("a@example.com")
    res = client.post("/companions/new", data={"name": "x" * 81, "description": "ok"}, follow_redirects=False)
    assert res.status_code == 303 and "error=" in res.headers["location"]
    assert db.query(Companion).count() == 0


def test_public_companion_usable_by_others_private_not(make_client, db):
    make_client("owner@example.com")
    other = make_client("other@example.com")
    owner = user_by_email(db, "owner@example.com")
    public = make_companion(db, owner, "Open", public=True)
    private = make_companion(db, owner, "Closed", public=False)

    res = other.post(f"/chat/{public.id}/new", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"].startswith("/chat/conversation/")
    res = other.post(f"/chat/{private.id}/new", follow_redirects=False)
    assert res.status_code == 404 and res.json()["error"]["code"] == "COMPANION_NOT_FOUND"


def test_companion_made_private_blocks_further_chat(make_client, db, fake_llm):
    make_client("owner@example.com")
    other = make_client("other@example.com")
    owner = user_by_email(db, "owner@example.com")
    companion = make_companion(db, owner, "Open", public=True)
    location = other.post(f"/chat/{companion.id}/new", follow_redirects=False).headers["location"]
    conversation_id = location.rsplit("/", 1)[1]

    companion.is_public = False
    db.commit()
    res = other.post("/api/chat", json={"conversation_id": conversation_id, "message": "still there?"})
    assert res.status_code == 404 and res.json()["error"]["code"] == "COMPANION_NOT_FOUND"
