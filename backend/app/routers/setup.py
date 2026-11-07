"""Persistent first-run setup. Only account creation and status are public."""

import json
import logging
from pathlib import Path
import subprocess
from threading import Lock
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..auth import current_user, hash_password
from ..config import get_settings
from ..db import get_session
from ..keydeploy import controller_public_key
from ..models import SetupState
from ..playbooks import list_playbooks
from ..repositories import DEFAULT_REPOSITORY, RepositoryInput, add_repository, list_repositories

settings = get_settings()
log = logging.getLogger(__name__)
lock = Lock()
router = APIRouter(prefix="/setup", tags=["setup"])
protected = [Depends(current_user)]


def state(s: Session) -> SetupState:
    return s.get(SetupState, 1) or SetupState()


@router.get("/status")
def status(s: Session = Depends(get_session)):
    stored = state(s)
    return {
        "required": not stored.completed,
        "needs_account": settings.needs_account,
        "default_repository": DEFAULT_REPOSITORY,
    }


class AccountInput(BaseModel):
    username: str = Field(default="admin", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)


@router.post("/account", status_code=201)
def create_account(body: AccountInput, request: Request):
    with lock:
        if not settings.needs_account:
            raise HTTPException(409, "Authentication is already configured")
        # JSON-only requests and an Origin check prevent cross-site first-run claims.
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "Setup must be opened from this server")
        password_hash = hash_password(body.password)
        path = settings.data_dir / "admin.json"
        try:
            with path.open("x", encoding="utf-8") as f:
                path.chmod(0o600)
                json.dump({"username": body.username, "password_hash": password_hash}, f)
        except FileExistsError as exc:
            raise HTTPException(409, "An administrator account already exists") from exc
        settings.admin_username = body.username
        settings.admin_password_hash = password_hash
        request.session.clear()
        request.session["user"] = {
            "sub": f"local:{body.username}", "name": body.username, "email": None, "groups": [],
        }
    return {"ok": True}


@router.get("/details", dependencies=protected)
def details(s: Session = Depends(get_session)):
    stored = state(s)
    return {
        "ssh_public_key": controller_public_key(),
        "repository_url": stored.repository_url,
        "repository_ref": stored.repository_ref,
        "repository_path": stored.repository_path,
        "repositories": list_repositories(s),
    }


@router.post("/ssh-key", dependencies=protected)
def ensure_ssh_key():
    with lock:
        key = Path(settings.ssh_key_path)
        key.parent.mkdir(parents=True, exist_ok=True)
        if not key.exists():
            try:
                subprocess.run(
                    ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "palma-controller", "-f", str(key)],
                    capture_output=True, text=True, check=True, timeout=15,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                log.exception("Controller SSH key generation failed")
                raise HTTPException(500, "SSH key generation failed; check the server logs") from exc
            key.chmod(0o600)
        try:
            public_key = subprocess.run(
                ["ssh-keygen", "-y", "-f", str(key)], input="", capture_output=True,
                text=True, check=True, timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(400, "Cannot read the provided SSH key; use an unencrypted private key") from exc
        if not public_key:
            raise HTTPException(400, "The provided SSH key is not usable; use an unencrypted private key")
        pub = Path(f"{key}.pub")
        if pub.exists() and pub.read_text().split()[:2] != public_key.split()[:2]:
            raise HTTPException(400, "The provided public key does not match the private key")
        if not pub.exists():
            pub.write_text(public_key + "\n", encoding="utf-8")
            pub.chmod(0o644)
        return {"ssh_public_key": public_key}


@router.post("/repository", dependencies=protected)
def configure_repository(body: RepositoryInput, s: Session = Depends(get_session)):
    record = add_repository(body, s)
    return {"repository_url": record.url, "repository_ref": record.ref, "repository_path": record.path}


@router.post("/complete", dependencies=protected)
def complete(s: Session = Depends(get_session)):
    with lock:
        stored = state(s)
        if not controller_public_key():
            raise HTTPException(400, "Create or provide a usable SSH key before finishing setup")
        if not list_playbooks():
            raise HTTPException(400, "Add local playbooks or a playbook repository before finishing setup")
        stored.completed = True
        s.add(stored)
        s.commit()
    return {"ok": True}
