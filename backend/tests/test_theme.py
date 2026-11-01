import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.theme import SystemTheme, ThemeSettings


@pytest.fixture()
def theme_client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'theme.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = session
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def test_theme_defaults_and_presets(theme_client):
    client, _ = theme_client
    data = client.get("/api/theme").json()
    assert data["theme"] == data["defaults"] == ThemeSettings().model_dump()
    assert {preset["id"] for preset in data["presets"]} == {"graphite", "midnight", "slate", "forest"}


def test_theme_persists_systemwide_and_resets(theme_client):
    client, engine = theme_client
    custom = {"primary": "#123456", "secondary": "#ABCDEF", "background": "midnight"}
    assert client.put("/api/theme", json=custom).json() == custom
    with Session(engine) as session:
        assert session.get(SystemTheme, 1).primary == "#123456"
    with TestClient(app) as another_client:
        assert another_client.get("/api/theme").json()["theme"] == custom
    assert client.delete("/api/theme").json() == ThemeSettings().model_dump()
    assert client.get("/api/theme").json()["theme"] == ThemeSettings().model_dump()
    with Session(engine) as session:
        assert session.get(SystemTheme, 1) is None
    assert client.delete("/api/theme").status_code == 200


@pytest.mark.parametrize("field,value", [
    ("primary", "red"), ("primary", "#fff"), ("secondary", "#123456;display:none"),
    ("background", "unknown"), ("primary", None), ("user_id", "user"),
])
def test_invalid_theme_is_not_saved(theme_client, field, value):
    client, _ = theme_client
    body = ThemeSettings().model_dump()
    body[field] = value
    assert client.put("/api/theme", json=body).status_code == 422
    assert client.get("/api/theme").json()["theme"] == ThemeSettings().model_dump()


def test_theme_public_read_protected_write(theme_client, monkeypatch):
    client, _ = theme_client
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "admin_password", "theme-test-password")
    assert client.get("/api/theme").status_code == 200
    assert client.put("/api/theme", json=ThemeSettings().model_dump()).status_code == 401
    assert client.delete("/api/theme").status_code == 401


def test_theme_survives_database_reopen(theme_client):
    client, engine = theme_client
    custom = {"primary": "#000000", "secondary": "#ffffff", "background": "forest"}
    assert client.put("/api/theme", json=custom).status_code == 200
    reopened = create_engine(engine.url)
    try:
        with Session(reopened) as session:
            stored = session.get(SystemTheme, 1)
            assert ThemeSettings.model_validate(stored, from_attributes=True).model_dump() == custom
    finally:
        reopened.dispose()
