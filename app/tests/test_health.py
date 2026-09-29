def test_liveness(client):
    assert client.get("/health/live").json() == {"status": "ok"}


def test_readiness_checks_database_and_migrations(client):
    res = client.get("/health/ready")
    assert res.status_code == 200
    checks = res.json()["checks"]
    assert checks["database"] == "ok" and checks["migrations"] == "ok"


def test_health_summary_has_no_secrets(client):
    body = client.get("/health").text
    assert "test-key" not in body and "test-secret" not in body
    assert client.get("/health").json()["voice_engine"] == "xtts"
