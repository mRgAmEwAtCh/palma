"""Compares the installed Ansible tooling against the latest upstream releases (PyPI / Ansible Galaxy)."""

import asyncio
import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any

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
