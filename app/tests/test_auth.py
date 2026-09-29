from datetime import timedelta

from conftest import PASSWORD, login, make_user, user_by_email
from models import UserSession, now


def test_signup_creates_account_and_session(client, db):
    res = client.post("/signup", data={"email": "  New@Example.com ", "password": PASSWORD}, follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/companions"
    user = user_by_email(db, "new@example.com")  # normalised
    assert db.query(UserSession).filter(UserSession.user_id == user.id).count() == 1
    assert client.get("/api/conversations").status_code == 200


def test_signup_rejects_invalid_email_and_short_password(client, db):
    res = client.post("/signup", data={"email": "not-an-email", "password": PASSWORD}, follow_redirects=False)
    assert "error=" in res.headers["location"]
    res = client.post("/signup", data={"email": "a@example.com", "password": "short"}, follow_redirects=False)
    assert "error=" in res.headers["location"]
    assert db.query(UserSession).count() == 0


def test_signup_rejects_duplicate_email_case_insensitively(client, db):
    make_user(db, "dup@example.com")
    res = client.post("/signup", data={"email": "DUP@example.com", "password": PASSWORD}, follow_redirects=False)
    assert "already+exists" in res.headers["location"]


def test_login_wrong_password_and_unknown_email_look_identical(client, db):
    make_user(db, "a@example.com")
    wrong = client.post("/login", data={"email": "a@example.com", "password": "nope-nope"}, follow_redirects=False)
    unknown = client.post("/login", data={"email": "b@example.com", "password": "nope-nope"}, follow_redirects=False)
    assert wrong.headers["location"] == unknown.headers["location"] == "/login?error=Invalid+email+or+password"


def test_session_cookie_is_httponly_and_lax(client, db):
    make_user(db, "a@example.com")
    res = client.post("/login", data={"email": "a@example.com", "password": PASSWORD}, follow_redirects=False)
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_logout_revokes_server_side_session(client, db):
    make_user(db, "a@example.com")
    login(client, "a@example.com")
    stolen = client.cookies.get("session")
    client.post("/logout")
    client.cookies.set("session", stolen)  # replaying the old cookie must not work
    assert client.get("/api/conversations").status_code == 401


def test_login_rotates_session(client, db):
    make_user(db, "a@example.com")
    login(client, "a@example.com")
    first = client.cookies.get("session")
    login(client, "a@example.com")
    assert client.cookies.get("session") != first
    sessions = db.query(UserSession).all()
    assert sum(1 for s in sessions if s.revoked_at is None) == 1


def test_expired_session_rejected(client, db):
    make_user(db, "a@example.com")
    login(client, "a@example.com")
    db.query(UserSession).update({UserSession.expires_at: now() - timedelta(seconds=1)})
    db.commit()
    assert client.get("/api/conversations").status_code == 401


def test_tampered_token_rejected(client, db):
    make_user(db, "a@example.com")
    login(client, "a@example.com")
    token = client.cookies.get("session")
    client.cookies.set("session", token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb"))
    assert client.get("/api/conversations").status_code == 401


def test_page_routes_redirect_anonymous_users_to_login(client):
    res = client.get("/companions", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/login"


def test_login_is_rate_limited(client, db):
    make_user(db, "a@example.com")
    statuses = [
        client.post("/login", data={"email": "a@example.com", "password": "wrong-pass"}, follow_redirects=False).status_code
        for _ in range(11)
    ]
    assert statuses[:10] == [303] * 10
    assert statuses[10] == 429
