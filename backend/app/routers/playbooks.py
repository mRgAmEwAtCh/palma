from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .. import playbook_editor as editor
from ..playbooks import list_playbooks, resolve_playbook

router = APIRouter(prefix="/playbooks", tags=["playbooks"])

MAX_SIZE = 256 * 1024


@router.get("")
def get_playbooks():
    return [p.dict() for p in list_playbooks()]


@router.get("/source", response_class=PlainTextResponse)
def get_playbook_source(path: str):
    try:
        return resolve_playbook(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(404, "Playbook not found") from exc


class ValidateRequest(BaseModel):
    content: str = Field(max_length=MAX_SIZE)
    name: str = "playbook.yml"


@router.post("/validate")
def validate_playbook(body: ValidateRequest):
    return editor.validate(body.content, body.name).dict()


class SaveRequest(BaseModel):
    name: str
    content: str = Field(max_length=MAX_SIZE)
    create: bool = False


@router.put("/file")
def save_playbook(body: SaveRequest):
    """Validates and saves; returns 422 with the validation result if there are errors."""
    try:
        result = editor.save(body.name, body.content, body.create)
    except editor.PlaybookFileError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "Playbook not found") from exc
    if not result.valid:
        raise HTTPException(422, {"message": "Validation failed", "validation": result.dict()})
    return {"saved": body.name, "validation": result.dict()}


@router.delete("/file", status_code=204)
def delete_playbook(name: str):
    try:
        editor.delete(name)
    except editor.PlaybookFileError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "Playbook not found") from exc
