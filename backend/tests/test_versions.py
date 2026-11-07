import pytest
from fastapi.testclient import TestClient

from app import versions
from app.main import app


@pytest.mark.parametrize(
    "installed,latest,expected",
    [
        ("2.21.5", "2.21.5", ("current", None)),
        ("2.21.6", "2.21.5", ("current", None)),
        ("2.21.4", "2.21.5", ("outdated", "patch")),
        ("2.20.9", "2.21.0", ("outdated", "minor")),
        ("12.9.0", "13.0.0", ("outdated", "major")),
        (None, "2.21.5", ("missing", None)),
        ("2.21.5", None, ("unknown", None)),
        ("weird", "2.21.5", ("unknown", None)),
    ],
)
def test_compare(installed, latest, expected):
    assert versions.compare(installed, latest) == expected


def test_versions_endpoint_offline_safe(monkeypatch):
    async def fake_pypi(client, name):
        return "99.0.0", "2026-01-01T00:00:00Z", f"https://pypi.org/project/{name}/"

    async def failing_galaxy(client, fqcn):
        raise versions.httpx2.ConnectError("offline")

    monkeypatch.setattr(versions, "_latest_pypi", fake_pypi)
    monkeypatch.setattr(versions, "_latest_galaxy", failing_galaxy)
    monkeypatch.setattr(versions, "_installed_collection", lambda fqcn: "1.0.0")

    with TestClient(app) as c:
        data = c.get("/api/system/versions", params={"refresh": "true"}).json()
    by_name = {comp["name"]: comp for comp in data["components"]}
    assert by_name["ansible-core"]["status"] == "outdated" and by_name["ansible-core"]["level"] == "major"
    assert by_name["ansible-core"]["installed"]
    assert by_name["community.general"]["status"] == "unknown"
    assert by_name["community.general"]["error"]
    assert data["update_available"] is True


@pytest.mark.parametrize(
    "current,latest,update",
    [
        ("v1.0.0", "v1.1.0", True),
        ("v1.1.0", "v1.1.0", False),
        ("v1.2.0", "v1.1.0", False),
        ("v1.9.0", "v1.10.0", True),
        ("v1.0.0-3-g1234567", "v1.1.0", False),
        ("v1.0.0-dirty", "v1.1.0", False),
        ("development", "v1.1.0", False),
    ],
)
def test_application_release_comparison(monkeypatch, current, latest, update):
    monkeypatch.setenv("PALMA_VERSION", current)
    monkeypatch.setattr(versions, "_app_cache", {"at": 0.0, "data": None})
    calls = []

    async def get(client, url, **kwargs):
        calls.append(url)
        return versions.httpx2.Response(
            200, json={"tag_name": latest, "draft": False, "prerelease": False},
            request=versions.httpx2.Request("GET", url),
        )

    monkeypatch.setattr(versions.httpx2.AsyncClient, "get", get)
    with TestClient(app) as client:
        response = client.get("/api/system/application-version")
        assert response.status_code == 200
        data = response.json()
        assert client.get("/api/system/application-version").json() == data
    assert len(calls) == 1
    assert data == {
        "current": current, "latest": latest, "update_available": update,
        "url": f"{versions.RELEASES_URL}/tag/{latest}", "error": None,
    }


@pytest.mark.parametrize("mode", ["offline", "rate-limit", "invalid-tag", "prerelease", "missing-tag"])
def test_application_release_check_failure(monkeypatch, mode):
    monkeypatch.setenv("PALMA_VERSION", "v1.0.0")
    monkeypatch.setattr(versions, "_app_cache", {"at": 0.0, "data": None})

    async def get(client, url, **kwargs):
        if mode == "offline":
            raise versions.httpx2.ConnectError("offline")
        payload = {"tag_name": "v2.0.0", "prerelease": mode == "prerelease"}
        if mode == "invalid-tag":
            payload["tag_name"] = "not-a-version"
        if mode == "missing-tag":
            payload = {}
        return versions.httpx2.Response(
            403 if mode == "rate-limit" else 200, json=payload,
            request=versions.httpx2.Request("GET", url),
        )

    monkeypatch.setattr(versions.httpx2.AsyncClient, "get", get)
    with TestClient(app) as client:
        response = client.get("/api/system/application-version")
    assert response.status_code == 200
    data = response.json()
    assert data["current"] == "v1.0.0"
    assert data["latest"] is None
    assert data["update_available"] is False
    assert data["error"]


def test_application_version_from_git(monkeypatch):
    monkeypatch.delenv("PALMA_VERSION", raising=False)
    monkeypatch.setattr(
        versions.subprocess, "run",
        lambda *args, **kwargs: versions.subprocess.CompletedProcess(args, 0, stdout="v1.1.0-2-gabc1234\n"),
    )
    assert versions.application_version() == "v1.1.0-2-gabc1234"
