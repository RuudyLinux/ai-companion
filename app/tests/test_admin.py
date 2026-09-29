from conftest import make_companion, make_voice, user_by_email
from models import AuditLog, Companion, UserSession, Voice


def test_normal_user_cannot_access_admin(make_client, db):
    client = make_client("u@example.com")
    assert client.get("/admin").status_code == 403
    assert client.get("/admin/roles").status_code == 403
    assert client.post("/admin/roles/update", data={"user_id": "x", "role": "admin"}).status_code == 403


def test_admin_cannot_access_super_admin_routes(make_client, db):
    client = make_client("admin@example.com", role="admin")
    target = make_client("u@example.com") and user_by_email(db, "u@example.com")
    assert client.get("/admin").status_code == 200
    assert client.get("/admin/roles").status_code == 403
    assert client.get("/admin/audit").status_code == 403
    res = client.post("/admin/roles/update", data={"user_id": target.id, "role": "super_admin"})
    assert res.status_code == 403
    db.expire_all()
    assert user_by_email(db, "u@example.com").role == "user"


def test_super_admin_cannot_change_own_role(make_client, db):
    client = make_client("root@example.com", role="super_admin")
    me = user_by_email(db, "root@example.com")
    res = client.post("/admin/roles/update", data={"user_id": me.id, "role": "user"}, follow_redirects=False)
    assert res.headers["location"] == "/admin/roles?error=self"
    db.expire_all()
    assert user_by_email(db, "root@example.com").role == "super_admin"


def test_role_change_is_audited_and_revokes_target_sessions(make_client, db):
    admin = make_client("root@example.com", role="super_admin")
    target_client = make_client("u@example.com")
    target = user_by_email(db, "u@example.com")

    res = admin.post("/admin/roles/update", data={"user_id": target.id, "role": "admin"}, follow_redirects=False)
    assert res.headers["location"] == "/admin/roles"
    db.expire_all()
    assert user_by_email(db, "u@example.com").role == "admin"

    entry = db.query(AuditLog).one()
    assert (entry.action, entry.actor_email, entry.target_id) == ("user.role_change", "root@example.com", target.id)
    assert (entry.before, entry.after) == ({"role": "user"}, {"role": "admin"})
    assert db.query(UserSession).filter(UserSession.user_id == target.id, UserSession.revoked_at.is_(None)).count() == 0
    assert target_client.get("/api/conversations").status_code == 401  # must sign in again
    assert "user.role_change" in admin.get("/admin/audit").text


def test_invalid_role_rejected(make_client, db):
    admin = make_client("root@example.com", role="super_admin")
    target = make_client("u@example.com") and user_by_email(db, "u@example.com")
    res = admin.post("/admin/roles/update", data={"user_id": target.id, "role": "god"}, follow_redirects=False)
    assert res.headers["location"] == "/admin/roles?error=invalid"


def test_admin_can_unpublish_companion_with_audit(make_client, db):
    admin = make_client("admin@example.com", role="admin")
    make_client("owner@example.com")
    companion = make_companion(db, user_by_email(db, "owner@example.com"), public=True)
    assert admin.post(f"/api/admin/companions/{companion.id}/unpublish").json() == {"ok": True}
    db.expire_all()
    assert db.get(Companion, companion.id).is_public is False
    assert db.query(AuditLog).filter(AuditLog.action == "companion.unpublish").count() == 1


def test_admin_voice_moderation_is_audited(make_client, db):
    admin = make_client("admin@example.com", role="admin")
    make_client("owner@example.com")
    voice_id = make_voice(db, owner=user_by_email(db, "owner@example.com")).id
    assert admin.delete(f"/api/admin/voices/{voice_id}").json() == {"ok": True}
    db.expire_all()
    assert db.query(Voice).filter(Voice.id == voice_id).count() == 0
    entry = db.query(AuditLog).filter(AuditLog.action == "voice.delete").one()
    assert entry.before["owner_id"] == user_by_email(db, "owner@example.com").id


def test_normal_user_cannot_moderate(make_client, db):
    client = make_client("u@example.com")
    companion = make_companion(db, user_by_email(db, "u@example.com"), public=True)
    assert client.post(f"/api/admin/companions/{companion.id}/unpublish").status_code == 403
