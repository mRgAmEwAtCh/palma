from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..db import get_session
from ..models import (
    Host,
    ProxmoxSource,
    ProxmoxSourceCreate,
    ProxmoxSourceRead,
    ProxmoxSourceUpdate,
    utcnow,
)
from ..proxmox import ProxmoxError, discover_guests, normalize_url

router = APIRouter(prefix="/proxmox", tags=["proxmox"])


def _get_source(s: Session, source_id: int) -> ProxmoxSource:
    src = s.get(ProxmoxSource, source_id)
    if not src:
        raise HTTPException(404, "Proxmox source not found")
    return src


@router.get("/sources", response_model=list[ProxmoxSourceRead])
def list_sources(s: Session = Depends(get_session)):
    return s.exec(select(ProxmoxSource).order_by(ProxmoxSource.name)).all()


@router.post("/sources", response_model=ProxmoxSourceRead, status_code=201)
def create_source(body: ProxmoxSourceCreate, s: Session = Depends(get_session)):
    src = ProxmoxSource.model_validate(body)
    src.url = normalize_url(src.url)
    s.add(src)
    try:
        s.commit()
    except IntegrityError as exc:
        raise HTTPException(409, f"A source named '{body.name}' already exists") from exc
    s.refresh(src)
    return src


@router.patch("/sources/{source_id}", response_model=ProxmoxSourceRead)
def update_source(source_id: int, body: ProxmoxSourceUpdate, s: Session = Depends(get_session)):
    src = _get_source(s, source_id)
    data = body.model_dump(exclude_unset=True)
    if not data.get("token_secret"):
        data.pop("token_secret", None)
    if data.get("url"):
        data["url"] = normalize_url(data["url"])
    src.sqlmodel_update(data)
    s.add(src)
    s.commit()
    s.refresh(src)
    return src


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: int, s: Session = Depends(get_session)):
    src = _get_source(s, source_id)
    for host in s.exec(select(Host).where(Host.proxmox_source_id == source_id)):
        host.proxmox_source_id = None
        host.source = "manual"
        s.add(host)
    s.delete(src)
    s.commit()


async def _discover(src: ProxmoxSource) -> dict:
    try:
        return await discover_guests(src)
    except ProxmoxError as exc:
        raise HTTPException(502, str(exc)) from exc


def _match_hosts(s: Session, source_id: int, guests: list[dict]) -> dict[int, Host]:
    """Maps vmid -> host: hosts already linked to the guest, else unlinked manual hosts with the same IP."""
    linked = {h.proxmox_vmid: h for h in s.exec(select(Host).where(Host.proxmox_source_id == source_id))}
    unlinked_by_ip = {h.address: h for h in s.exec(select(Host).where(Host.proxmox_source_id == None))}  # noqa: E711
    result: dict[int, Host] = {}
    for g in guests:
        host = linked.get(g["vmid"]) or (unlinked_by_ip.get(g["ip"]) if g["ip"] else None)
        if host:
            result[g["vmid"]] = host
    return result


@router.get("/sources/{source_id}/discover")
async def discover(source_id: int, s: Session = Depends(get_session)):
    src = _get_source(s, source_id)
    found = await _discover(src)
    matches = _match_hosts(s, source_id, found["guests"])
    for g in found["guests"]:
        host = matches.get(g["vmid"])
        g["host_id"] = host.id if host else None
    return found


class ImportRequest(BaseModel):
    vmids: list[int]


@router.post("/sources/{source_id}/import")
async def import_guests(source_id: int, body: ImportRequest, s: Session = Depends(get_session)):
    """Creates hosts for new guests and refreshes node/status/address/type of already imported ones."""
    src = _get_source(s, source_id)
    wanted = set(body.vmids)
    guests = [g for g in (await _discover(src))["guests"] if g["vmid"] in wanted]
    by_vmid = _match_hosts(s, source_id, guests)
    taken = set(s.exec(select(Host.name)).all())
    created, updated, skipped = 0, 0, []

    for g in guests:
        host = by_vmid.get(g["vmid"])
        if host:
            if host.proxmox_source_id is None:  # adopt a manually added host with the same IP
                host.source = "proxmox"
                host.proxmox_source_id = src.id
                host.proxmox_vmid = g["vmid"]
                host.tags = sorted({*(host.tags or []), "proxmox", src.name, *g["tags"]})
            host.proxmox_type = g["type"]
            host.proxmox_node = g["node"]
            host.proxmox_status = g["status"]
            if g["ip"]:
                host.address = g["ip"]
            updated += 1
        else:
            if not g["manageable"]:
                skipped.append({"vmid": g["vmid"], "name": g["name"], "reason": g["note"] or "not manageable"})
                continue
            if not g["ip"]:
                skipped.append({"vmid": g["vmid"], "name": g["name"], "reason": g["note"] or "no IPv4 address found"})
                continue
            name = g["name"] if g["name"] not in taken else f"{g['name']}-{src.name}-{g['vmid']}"
            taken.add(name)
            host = Host(
                name=name,
                address=g["ip"],
                ssh_user=src.default_ssh_user,
                kind="vm" if g["type"] == "qemu" else "lxc",
                tags=sorted({"proxmox", src.name, *g["tags"]}),
                source="proxmox",
                proxmox_source_id=src.id,
                proxmox_type=g["type"],
                proxmox_node=g["node"],
                proxmox_vmid=g["vmid"],
                proxmox_status=g["status"],
                os_name=g["ostype"],
            )
            created += 1
        s.add(host)

    src.last_sync = utcnow()
    s.add(src)
    s.commit()
    return {"created": created, "updated": updated, "skipped": skipped}
