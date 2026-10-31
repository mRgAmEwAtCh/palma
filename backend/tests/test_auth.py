import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


@pytest.fixture()
def local_client(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "s3cret-pw")
    with TestClient(app) as c:
        yield c


def test_local_mode_requires_login(local_client):
    assert local_client.get("/auth/config").json() == {"mode": "local"}
    assert local_client.get("/api/hosts").status_code == 401
    r = local_client.get("/auth/login", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/login"


def test_local_login_wrong_password(local_client):
    r = local_client.post("/auth/local", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401
    assert local_client.get("/api/hosts").status_code == 401


def test_local_login_and_logout(local_client):
    assert local_client.post("/auth/local", json={"username": "admin", "password": "s3cret-pw"}).status_code == 200
    me = local_client.get("/api/me").json()
    assert me["name"] == "admin" and me["auth_mode"] == "local"
    assert local_client.get("/api/hosts").status_code == 200
    r = local_client.get("/auth/logout", follow_redirects=False)
    assert r.headers["location"] == "/login"
    assert local_client.get("/api/hosts").status_code == 401


def test_oidc_mode_selected_when_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.example.com/application/o/x/")
    monkeypatch.setattr(settings, "oidc_client_id", "abc")
    assert settings.auth_mode == "oidc"
    with TestClient(app) as c:
        assert c.post("/auth/local", json={"username": "admin", "password": "x"}).status_code == 404
