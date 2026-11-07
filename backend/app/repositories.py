"""Additive Git snapshots alongside bind-mounted local playbook sources."""

import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from .config import get_settings
from .models import PlaybookRepository, Run, Schedule, SetupState, utcnow
from .playbooks import list_playbooks, source_folders

DEFAULT_REPOSITORY = "https://github.com/mrgamewatch/palma.git"
BUNDLED_PLAYBOOKS = Path("/app/default-playbooks")
settings = get_settings()
log = logging.getLogger(__name__)
lock = Lock()


class RepositoryInput(BaseModel):
    name: str = Field(default="", max_length=64, pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,63})?$")
    url: str = DEFAULT_REPOSITORY
    ref: str = Field(default="", max_length=200)
    path: str = Field(default="playbooks", max_length=200)


def migrate_repository(s: Session) -> None:
    """Retain metadata for the previous single-source snapshot without moving its files."""
    stored = s.get(SetupState, 1)
    if stored and stored.repository_url and not s.exec(select(PlaybookRepository)).first():
        s.add(PlaybookRepository(
            name="local", url=stored.repository_url, ref=stored.repository_ref,
            path=stored.repository_path, folder="",
        ))
        s.commit()
    bundled = settings.playbooks_dir / "sources" / "palma"
    if (bundled / ".palma-bundled").is_file() and not s.exec(select(PlaybookRepository).where(
        PlaybookRepository.folder == "sources/palma",
    )).first():
        s.add(PlaybookRepository(name="palma", url=DEFAULT_REPOSITORY, folder="sources/palma"))
        s.commit()


def checkout_repository(body: RepositoryInput, checkout: Path) -> Path:
    command = ["git", "clone", "--single-branch"]
    if body.ref:
        command += ["--branch", body.ref]
    command += ["--", body.url, str(checkout)]
    try:
        subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=120,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.exception("Playbook repository clone failed")
        raise HTTPException(502, "Cannot clone repository; check its URL, branch, access and server logs") from exc
    raw = checkout / body.path
    source = raw.resolve()
    if not source.is_relative_to(checkout.resolve()) or not source.is_dir() or raw.is_symlink():
        raise HTTPException(400, "Playbook folder does not exist inside the repository")
    if any(p.is_symlink() for p in source.rglob("*")):
        raise HTTPException(400, "Repository playbook folder must not contain symbolic links")
    if not list_playbooks(source):
        raise HTTPException(400, "Selected folder contains no top-level Ansible playbooks")
    return source


def list_repositories(s: Session) -> list[dict]:
    with lock:
        return _list_repositories(s)


def _list_repositories(s: Session) -> list[dict]:
    migrate_repository(s)
    records = list(s.exec(select(PlaybookRepository).order_by(PlaybookRepository.id)))
    known = {r.folder for r in records}
    sources = [] if "" in known else [
        {"id": None, "name": "local", "kind": "local", "folder": "", "url": "", "ref": "", "path": ""},
    ]
    for r in records:
        sources.append({
            "id": r.id, "name": r.name, "kind": "git", "folder": r.folder,
            "url": r.url, "ref": r.ref, "path": r.path,
        })
    for label, folder in source_folders():
        relative = folder.relative_to(settings.playbooks_dir.resolve()).as_posix()
        if relative not in known:
            sources.append({
                "id": None, "name": label, "kind": "local", "folder": relative, "url": "", "ref": "", "path": "",
            })
    return sources


def add_repository(body: RepositoryInput, s: Session) -> PlaybookRepository:
    url = body.url.strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(400, "Use an HTTP(S) Git URL without embedded credentials, query or fragment")
    rel = Path(body.path)
    if rel.is_absolute() or ".." in rel.parts or "\\" in body.path:
        raise HTTPException(400, "Playbook folder must be a relative path inside the repository")
    if body.ref.startswith("-"):
        raise HTTPException(400, "Invalid Git branch or tag")
    with lock:
        migrate_repository(s)
        existing = s.exec(select(PlaybookRepository).where(
            PlaybookRepository.url == url, PlaybookRepository.ref == body.ref, PlaybookRepository.path == body.path,
        )).first()
        if existing:
            return existing
        bundled = url == DEFAULT_REPOSITORY and not body.ref and body.path == "playbooks"
        root = settings.playbooks_dir.resolve()
        name = body.name or ("palma" if bundled else f"repo-{uuid4().hex[:8]}")
        folder = f"sources/{name}"
        record = PlaybookRepository(name=name, url=url, ref=body.ref, path=body.path, folder=folder)
        if name.lower() == "local":
            raise HTTPException(409, "The source name 'local' is reserved")
        sources = root / "sources"
        if sources.is_symlink():
            raise HTTPException(400, "The sources directory must not be a symbolic link")
        sources.mkdir(parents=True, exist_ok=True)
        if any(p.name.lower() == name.lower() for p in sources.iterdir()) or any(
            r.name.lower() == name.lower() for r in s.exec(select(PlaybookRepository))
        ):
            raise HTTPException(409, "A source with that name already exists; choose a different name")
        destination = root / folder
        with tempfile.TemporaryDirectory(prefix="palma-repo-", dir=settings.data_dir) as temporary:
            checkout = Path(temporary) / "checkout"
            if bundled:
                source = BUNDLED_PLAYBOOKS
                if not source.is_dir():
                    raise HTTPException(400, "Bundled playbooks are unavailable; add the repository with a branch to clone it")
            else:
                source = checkout_repository(body.model_copy(update={"url": url}), checkout)
            incoming = sources / f".import-{uuid4().hex}"
            installed = False
            try:
                shutil.copytree(source, incoming, ignore=shutil.ignore_patterns(".git"))
                incoming.rename(destination)
                installed = True
                s.add(record)
                s.commit()
                s.refresh(record)
            except (OSError, SQLAlchemyError) as exc:
                s.rollback()
                if installed:
                    shutil.rmtree(destination)
                log.exception("Playbook repository import failed")
                raise HTTPException(500, "Repository import failed; existing sources were not changed") from exc
            finally:
                if incoming.exists():
                    shutil.rmtree(incoming)
        return record


def pull_repository(repository_id: int, s: Session) -> dict:
    with lock:
        record = s.get(PlaybookRepository, repository_id)
        if not record:
            raise HTTPException(404, "Playbook repository not found")
        root = settings.playbooks_dir.resolve()
        legacy = not record.folder
        folder = record.folder or f"sources/legacy-{record.id}"
        destination = root / folder
        if (root / "sources").is_symlink() or destination.is_symlink():
            raise HTTPException(400, "Repository folders must not be symbolic links")
        if legacy and destination.exists():
            raise HTTPException(409, "The legacy migration folder already exists")

        def check_active() -> None:
            if s.exec(select(Run).where(Run.status.in_(["pending", "running"]))).first():
                raise HTTPException(409, "Wait for active runs to finish before pulling playbooks")
            prefix = folder + "/"
            if not legacy and any(
                schedule.playbook.startswith(prefix) for schedule in s.exec(
                    select(Schedule).where(Schedule.enabled == True)  # noqa: E712
                )
            ):
                raise HTTPException(409, "Disable schedules using this source before pulling; re-enable them after reviewing updates")

        check_active()
        body = RepositoryInput(name=record.name, url=record.url, ref=record.ref, path=record.path)
        with tempfile.TemporaryDirectory(prefix="palma-pull-", dir=settings.data_dir) as temporary:
            source = checkout_repository(body, Path(temporary) / "checkout")
            destination.parent.mkdir(parents=True, exist_ok=True)
            incoming = destination.parent / f".import-{uuid4().hex}"
            previous = destination.parent / f".previous-{uuid4().hex}"
            backup = settings.data_dir / "playbook-backups" / str(record.id) / uuid4().hex
            moved_old = installed = False
            try:
                shutil.copytree(source, incoming, ignore=shutil.ignore_patterns(".git"))
                check_active()
                if destination.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(destination, backup)
                    destination.rename(previous)
                    moved_old = True
                incoming.rename(destination)
                installed = True
                if legacy:
                    record.folder = folder
                    record.name = f"legacy-{record.id}"
                s.add(record)
                s.commit()
            except (OSError, SQLAlchemyError) as exc:
                s.rollback()
                try:
                    if installed:
                        shutil.rmtree(destination)
                    if moved_old:
                        previous.rename(destination)
                except OSError as restore_error:
                    log.exception("Repository restoration failed")
                    raise HTTPException(500, "Pull and restore failed; recover files from playbook-backups") from restore_error
                log.exception("Repository pull failed")
                raise HTTPException(500, "Repository pull failed; previous playbooks were restored") from exc
            finally:
                if incoming.exists():
                    shutil.rmtree(incoming)
            if previous.exists():
                shutil.rmtree(previous)
        return {
            "id": record.id, "folder": record.folder,
            "backup": str(backup.relative_to(settings.data_dir)) if moved_old else None,
            "updated_at": utcnow().isoformat(),
            "legacy_migrated": legacy,
        }
