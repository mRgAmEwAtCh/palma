from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from .. import playbook_editor as editor
from ..playbooks import list_playbooks, resolve_playbook
from ..db import get_session
from ..models import PlaybookRepository
from ..repositories import RepositoryInput, add_repository, list_repositories, pull_repository, lock

router = APIRouter(prefix="/playbooks", tags=["playbooks"])

MAX_SIZE = 256 * 1024


@router.get("/repositories")
def repositories(s: Session = Depends(get_session)):
    return list_repositories(s)


@router.post("/repositories", response_model=PlaybookRepository, status_code=201)
def create_repository(body: RepositoryInput, s: Session = Depends(get_session)):
    return add_repository(body, s)


@router.post("/repositories/{repository_id}/pull")
def pull(repository_id: int, s: Session = Depends(get_session)):
    return pull_repository(repository_id, s)


@router.get("")
def get_playbooks():
    return [p.dict() for p in list_playbooks()]


@router.get("/source", response_class=PlainTextResponse)
def get_playbook_source(path: str):
    try:
        return resolve_playbook(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(404, "Playbook not found") from exc
    except OSError as exc:
        raise HTTPException(409, "Cannot read playbook; check source permissions") from exc


class ValidateRequest(BaseModel):
    content: str = Field(max_length=MAX_SIZE)
    name: str = "playbook.yml"


@router.post("/validate")
def validate_playbook(body: ValidateRequest):
    try:
        with lock:
            editor.check_name(body.name)
            return editor.validate(body.content, body.name).dict()
    except editor.PlaybookFileError as exc:
        raise HTTPException(400, str(exc)) from exc


class SaveRequest(BaseModel):
    name: str
    content: str = Field(max_length=MAX_SIZE)
    create: bool = False


@router.put("/file")
def save_playbook(body: SaveRequest):
    """Validates and saves; returns 422 with the validation result if there are errors."""
    try:
        with lock:
            result = editor.save(body.name, body.content, body.create)
    except editor.PlaybookFileError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "Playbook not found") from exc
    except OSError as exc:
        raise HTTPException(409, "Cannot save playbook; check source permissions and available disk space") from exc
    if not result.valid:
        raise HTTPException(422, {"message": "Validation failed", "validation": result.dict()})
    return {"saved": body.name, "validation": result.dict()}


@router.delete("/file", status_code=204)
def delete_playbook(name: str):
    try:
        with lock:
            editor.delete(name)
    except editor.PlaybookFileError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "Playbook not found") from exc
    except OSError as exc:
        raise HTTPException(409, "Cannot delete playbook; check source permissions") from exc
