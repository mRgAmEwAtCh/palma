import asyncio
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from ..config import get_settings
from ..db import get_session
from ..keydeploy import DeployResult, Target, controller_public_key, deploy_via_proxmox_node, deploy_via_ssh
from ..models import Host, ProxmoxSource, utcnow
from ..proxmox import ProxmoxError, node_addresses

router = APIRouter(prefix="/keys", tags=["keys"])
settings = get_settings()


class DeployRequest(BaseModel):
    host_ids: list[int] = Field(min_length=1)
    method: Literal["ssh", "proxmox"]
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    ensure_sshd: bool = True


def _target(h: Host, user: str) -> Target:
    return Target(h.id, h.name, h.address, h.port, user, h.proxmox_vmid, h.proxmox_type or "lxc")


async def _via_ssh(hosts: list[Host], body: DeployRequest, key: str) -> list[DeployResult]:
    limit = asyncio.Semaphore(5)

    async def one(h: Host) -> DeployResult:
        async with limit:
            # The key is installed for the login user, who then becomes the host's SSH user.
            return await deploy_via_ssh(_target(h, body.username), body.password, key)

    return list(await asyncio.gather(*(one(h) for h in hosts)))


async def _via_proxmox(s: Session, hosts: list[Host], body: DeployRequest, key: str) -> list[DeployResult]:
    results: list[DeployResult] = []
    by_node: dict[tuple[int, str], list[Host]] = defaultdict(list)
    for h in hosts:
        if h.proxmox_source_id is None or h.proxmox_vmid is None or not h.proxmox_node:
            results.append(DeployResult(h.id, h.name, False, False, "not an imported Proxmox guest"))
        else:
            by_node[(h.proxmox_source_id, h.proxmox_node)].append(h)

    addresses: dict[int, dict[str, str]] = {}
    jobs = []
    for (source_id, node), node_hosts in by_node.items():
        if source_id not in addresses:
            src = s.get(ProxmoxSource, source_id)
            try:
                addresses[source_id] = await node_addresses(src) if src else {}
            except ProxmoxError as exc:
                raise HTTPException(502, str(exc)) from exc
        address = addresses[source_id].get(node)
        if not address:
            results += [DeployResult(h.id, h.name, False, False, f"no IP known for node {node}") for h in node_hosts]
            continue
        targets = [_target(h, h.ssh_user or settings.default_ssh_user) for h in node_hosts]
        jobs.append(deploy_via_proxmox_node(address, body.username, body.password, targets, key, body.ensure_sshd))

    for node_results in await asyncio.gather(*jobs):
        results += node_results
    return results


@router.post("/deploy")
async def deploy_key(body: DeployRequest, s: Session = Depends(get_session)):
    key = controller_public_key()
    if not key:
        raise HTTPException(400, f"No controller key found at {settings.ssh_key_path}")
    hosts = list(s.exec(select(Host).where(col(Host.id).in_(body.host_ids))))
    if len(hosts) != len(set(body.host_ids)):
        raise HTTPException(400, "Some selected hosts do not exist")

    if body.method == "ssh":
        results = await _via_ssh(hosts, body, key)
    else:
        results = await _via_proxmox(s, hosts, body, key)

    by_id = {h.id: h for h in hosts}
    for r in results:
        host = by_id[r.host_id]
        if r.ok and body.method == "ssh" and body.username != (host.ssh_user or settings.default_ssh_user):
            host.ssh_user = body.username
        if r.verified:
            host.last_error = None
            host.last_seen = utcnow()
        s.add(host)
    s.commit()

    order = {hid: i for i, hid in enumerate(body.host_ids)}
    results.sort(key=lambda r: order.get(r.host_id, 0))
    return {"results": [r.dict() for r in results]}
