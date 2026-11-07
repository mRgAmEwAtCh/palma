"""Compares the installed Ansible tooling against the latest upstream releases (PyPI / Ansible Galaxy)."""

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx2
from packaging.version import InvalidVersion, Version

log = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 6 * 3600
GALAXY_INDEX = "https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/collections/index"

COMPONENTS: list[dict[str, str]] = [
    {"name": "ansible-core", "source": "pypi", "description": "Ansible engine"},
    {"name": "ansible-runner", "source": "pypi", "description": "Runs playbooks for this app"},
    {"name": "community.general", "source": "galaxy", "description": "Collection (apk module etc.)"},
]

_cache: dict[str, Any] = {"at": 0.0, "data": None}
_lock = asyncio.Lock()
_app_cache: dict[str, Any] = {"at": 0.0, "data": None}
_app_lock = asyncio.Lock()
RELEASES_URL = "https://github.com/mRgAmEwAtCh/palma/releases"


def application_version() -> str:
    configured = os.environ.get("PALMA_VERSION")
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--match", "v[0-9]*", "--always", "--dirty"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Could not determine Palma Git version: %s", exc)
        return "development"


async def check_application_version() -> dict[str, Any]:
    async with _app_lock:
        if _app_cache["data"] and time.monotonic() - _app_cache["at"] < CACHE_TTL_SECONDS:
            return _app_cache["data"]
        current = application_version()
        latest = error = None
        url = RELEASES_URL
        status = "unknown"
        try:
            async with httpx2.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(
                    "https://api.github.com/repos/mRgAmEwAtCh/palma/releases/latest",
                    headers={"Accept": "application/vnd.github+json"},
                )
                response.raise_for_status()
                release = response.json()
                latest = release["tag_name"]
                if (
                    not isinstance(latest, str)
                    or not re.fullmatch(r"v?\d+\.\d+\.\d+", latest)
                    or release.get("draft") or release.get("prerelease")
                ):
                    raise ValueError("Latest release is not a stable version tag")
                url = f"{RELEASES_URL}/tag/{quote(latest, safe='')}"
                if re.fullmatch(r"v?\d+\.\d+\.\d+", current):
                    status, _ = compare(current, latest)
        except (httpx2.HTTPError, KeyError, TypeError, ValueError) as exc:
            error = f"Could not check Palma releases: {exc.__class__.__name__}"
            log.warning("%s: %s", error, exc)
            latest = None
        data = {
            "current": current, "latest": latest, "url": url,
            "update_available": status == "outdated", "error": error,
        }
        _app_cache.update(at=time.monotonic(), data=data)
        return data


def compare(installed: str | None, latest: str | None) -> tuple[str, str | None]:
    """Returns (status, level) with status in current|outdated|missing|unknown and level in major|minor|patch."""
    if not installed:
        return "missing", None
    if not latest:
        return "unknown", None
    try:
        i, l = Version(installed), Version(latest)
    except InvalidVersion:
        return "unknown", None
    if i >= l:
        return "current", None
    if l.major > i.major:
        return "outdated", "major"
    if l.minor > i.minor:
        return "outdated", "minor"
    return "outdated", "patch"


def _installed_package(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _installed_collection(fqcn: str) -> str | None:
    """Uses ansible-galaxy so the configured collection paths are respected; first path wins, like Ansible."""
    try:
        r = subprocess.run(
            ["ansible-galaxy", "collection", "list", fqcn, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for collections in json.loads(r.stdout or "{}").values():
            if fqcn in collections:
                return collections[fqcn].get("version")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        log.warning("Could not determine installed version of %s: %s", fqcn, exc)
    return None


async def _latest_pypi(client: httpx2.AsyncClient, name: str) -> tuple[str, str | None, str]:
    r = await client.get(f"https://pypi.org/pypi/{name}/json")
    r.raise_for_status()
    data = r.json()
    latest = data["info"]["version"]
    files = data.get("releases", {}).get(latest) or [{}]
    return latest, files[0].get("upload_time_iso_8601"), f"https://pypi.org/project/{name}/{latest}/"


async def _latest_galaxy(client: httpx2.AsyncClient, fqcn: str) -> tuple[str, str | None, str]:
    namespace, name = fqcn.split(".", 1)
    r = await client.get(f"{GALAXY_INDEX}/{namespace}/{name}/")
    r.raise_for_status()
    data = r.json()
    latest = data["highest_version"]["version"]
    return latest, data.get("updated_at"), f"https://galaxy.ansible.com/ui/repo/published/{namespace}/{name}/"


async def _check_component(client: httpx2.AsyncClient, comp: dict[str, str]) -> dict[str, Any]:
    is_pypi = comp["source"] == "pypi"
    installed = await asyncio.to_thread(_installed_package if is_pypi else _installed_collection, comp["name"])
    latest = released = url = error = None
    try:
        latest, released, url = await (_latest_pypi if is_pypi else _latest_galaxy)(client, comp["name"])
    except (httpx2.HTTPError, KeyError, ValueError) as exc:
        error = f"Could not fetch latest release: {exc.__class__.__name__}"
    status, level = compare(installed, latest)
    return {
        **comp,
        "installed": installed,
        "latest": latest,
        "latest_released": released,
        "url": url,
        "status": status,
        "level": level,
        "error": error,
    }


async def check_versions(refresh: bool = False) -> dict[str, Any]:
    async with _lock:
        if not refresh and _cache["data"] and time.monotonic() - _cache["at"] < CACHE_TTL_SECONDS:
            return _cache["data"]
        async with httpx2.AsyncClient(timeout=10, follow_redirects=True) as client:
            components = await asyncio.gather(*(_check_component(client, c) for c in COMPONENTS))
        data = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "update_available": any(c["status"] == "outdated" for c in components),
            "components": components,
        }
        _cache.update(at=time.monotonic(), data=data)
        return data
