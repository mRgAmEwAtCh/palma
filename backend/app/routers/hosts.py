from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..db import get_session
from ..models import Host, HostCreate, HostRead, HostUpdate

router = APIRouter(prefix="/hosts", tags=["hosts"])


def _clean_tags(tags: list[str]) -> list[str]:
    return sorted({t.strip() for t in tags if t and t.strip()})


@router.get("", response_model=list[HostRead])
def list_hosts(s: Session = Depends(get_session)):
    return s.exec(select(Host).order_by(Host.name)).all()


@router.post("", response_model=HostRead, status_code=201)
def create_host(body: HostCreate, s: Session = Depends(get_session)):
    host = Host.model_validate(body)
    host.tags = _clean_tags(host.tags)
    s.add(host)
    try:
        s.commit()
    except IntegrityError as exc:
        raise HTTPException(409, f"A host named '{body.name}' already exists") from exc
    s.refresh(host)
    return host


@router.get("/{host_id}", response_model=HostRead)
def get_host(host_id: int, s: Session = Depends(get_session)):
    host = s.get(Host, host_id)
    if not host:
        raise HTTPException(404, "Host not found")
    return host


@router.patch("/{host_id}", response_model=HostRead)
def update_host(host_id: int, body: HostUpdate, s: Session = Depends(get_session)):
    host = s.get(Host, host_id)
    if not host:
        raise HTTPException(404, "Host not found")
    data = body.model_dump(exclude_unset=True)
    if "tags" in data:
        data["tags"] = _clean_tags(data["tags"] or [])
    host.sqlmodel_update(data)
    s.add(host)
    try:
        s.commit()
    except IntegrityError as exc:
        raise HTTPException(409, f"A host named '{body.name}' already exists") from exc
    s.refresh(host)
    return host


@router.delete("/{host_id}", status_code=204)
def delete_host(host_id: int, s: Session = Depends(get_session)):
    host = s.get(Host, host_id)
    if not host:
        raise HTTPException(404, "Host not found")
    s.delete(host)
    s.commit()
