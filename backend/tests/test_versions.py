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
        raise versions.httpx.ConnectError("offline")

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
