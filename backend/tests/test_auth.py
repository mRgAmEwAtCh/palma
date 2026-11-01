import asyncio
from urllib.parse import parse_qs

import httpx2
import pytest
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_authlib_token_exchange_uses_httpx2():
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://auth.example.com/token"
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["test-code"]
        assert form["client_id"] == ["test-client"]
        assert form["client_secret"] == ["test-secret"]
        return httpx2.Response(
            200, json={"access_token": "test-token", "token_type": "Bearer", "expires_in": 3600}
        )

    async def exchange():
        async with AsyncOAuth2Client(
            client_id="test-client",
            client_secret="test-secret",
            token_endpoint_auth_method="client_secret_post",
            transport=httpx2.MockTransport(handler),
        ) as client:
            assert isinstance(client, httpx2.AsyncClient)
            token = await client.fetch_token("https://auth.example.com/token", code="test-code")
            assert token["access_token"] == "test-token"

    asyncio.run(exchange())


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
