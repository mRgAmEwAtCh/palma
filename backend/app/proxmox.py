"""Discovers LXC containers and QEMU VMs via the Proxmox VE API."""

import ipaddress
import re
from typing import Any

import httpx

from .models import ProxmoxSource


class ProxmoxError(Exception):
    pass


# Interfaces that never carry the management address of a guest (container runtimes, bridges, VPNs).
_IGNORED_IFACE = re.compile(r"^(lo|docker\d*|br-.*|veth.*|virbr.*|cni.*|flannel.*|cali.*|vxlan.*|hassio|tailscale.*|wg.*|zt.*)$")


def _usable_ipv4(value: str) -> str | None:
    try:
        ip = ipaddress.IPv4Address(value.split("/")[0])
    except ValueError:
        return None
    return None if ip.is_loopback or ip.is_link_local else str(ip)


def _first_ipv4(interfaces: list[dict]) -> str | None:
    """LXC `/interfaces` (inet) and guest-agent `network-get-interfaces` (ip-addresses) formats."""
    for iface in interfaces or []:
        if _IGNORED_IFACE.match(iface.get("name") or ""):
            continue
        if iface.get("inet") and (ip := _usable_ipv4(iface["inet"])):
            return ip
        for addr in iface.get("ip-addresses") or []:
            if addr.get("ip-address-type") == "ipv4" or addr.get("ip-address-type") == "inet":
                if ip := _usable_ipv4(addr.get("ip-address", "")):
                    return ip
    return None


def _static_ip_from_config(config: dict, prefix: str) -> str | None:
    """LXC: net0 "...,ip=192.168.1.5/24"; VM: cloud-init ipconfig0 "ip=192.168.1.5/24,gw=..."."""
    for key in sorted(k for k in config if re.fullmatch(rf"{prefix}\d+", k)):
        m = re.search(r"(?:^|,)ip=([0-9.]+)/\d+", str(config[key]))
        if m:
            return m.group(1)
    return None


def _tags(value: str | None) -> list[str]:
    return [t for t in re.split(r"[;,\s]+", value or "") if t]


def normalize_url(url: str) -> str:
    """Accepts host[:port], full URLs and URLs copied with the /api2/json suffix."""
    url = url.strip().rstrip("/")
    url = re.sub(r"/api2(/json)?$", "", url, flags=re.IGNORECASE)
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = f"https://{url}"
    return url


def _missing_permission_hint(src: ProxmoxSource) -> str:
    return (
        f"The API token '{src.token_id}' has no VM.Audit permission, so Proxmox hides all guests. "
        "Grant the role PVEAuditor on path '/' to the token (Datacenter → Permissions → Add → API Token Permission), "
        f"e.g. pveum acl modify / --tokens '{src.token_id}' --roles PVEAuditor. "
        "With privilege separation enabled the user needs that permission as well."
    )


def _client(src: ProxmoxSource, transport: httpx.AsyncBaseTransport | None) -> tuple[httpx.AsyncClient, str]:
    base = normalize_url(src.url) + "/api2/json"
    headers = {"Authorization": f"PVEAPIToken={src.token_id}={src.token_secret}"}
    return httpx.AsyncClient(base_url=base, headers=headers, verify=src.verify_ssl, timeout=15, transport=transport), base


async def discover_guests(src: ProxmoxSource, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    """Returns {"nodes": [...], "guests": [...], "warning": str | None}.

    Each guest: vmid, type (lxc|qemu), node, name, status, ip, ostype, tags, manageable, note.
    """
    client, base = _client(src, transport)
    async with client as c:

        async def get(path: str) -> Any:
            r = await c.get(path)
            if r.status_code == 401:
                raise ProxmoxError("Authentication failed (check token id/secret)")
            r.raise_for_status()
            return r.json()["data"]

        async def get_or_none(path: str) -> Any:
            try:
                return await get(path)
            except httpx.HTTPError:
                return None

        try:
            nodes = await get("/nodes")
        except httpx.HTTPStatusError as exc:
            raise ProxmoxError(f"Proxmox API error at {base}: HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise ProxmoxError(f"Cannot reach {base}: {exc}") from exc

        node_names: list[str] = []
        guests: list[dict[str, Any]] = []
        for node in nodes:
            if node.get("status") != "online":
                continue
            name = node["node"]
            node_names.append(name)
            for ct in await get(f"/nodes/{name}/lxc"):
                guests.append(await _lxc(get_or_none, name, ct))
            for vm in await get_or_none(f"/nodes/{name}/qemu") or []:
                if vm.get("template"):
                    continue
                guests.append(await _qemu(c, get_or_none, name, vm))
        guests.sort(key=lambda x: x["vmid"])

        warning = None
        if not guests:
            perms = await get_or_none("/access/permissions")
            has_audit = perms is None or any((p or {}).get("VM.Audit") for p in perms.values())
            if not node_names:
                warning = "No online nodes visible to this token (needs Sys.Audit, e.g. role PVEAuditor on '/')."
            elif not has_audit:
                warning = _missing_permission_hint(src)
            else:
                warning = f"No containers or VMs found on node(s): {', '.join(node_names)}."
        return {"nodes": node_names, "guests": guests, "warning": warning}


async def _lxc(get_or_none, node: str, ct: dict) -> dict[str, Any]:
    vmid = int(ct["vmid"])
    config = await get_or_none(f"/nodes/{node}/lxc/{vmid}/config") or {}
    ip = None
    if ct.get("status") == "running":
        ip = _first_ipv4(await get_or_none(f"/nodes/{node}/lxc/{vmid}/interfaces") or [])
    ip = ip or _static_ip_from_config(config, "net")
    return {
        "vmid": vmid,
        "type": "lxc",
        "node": node,
        "name": ct.get("name") or config.get("hostname") or f"ct{vmid}",
        "status": ct.get("status"),
        "ip": ip,
        "ostype": config.get("ostype"),
        "tags": _tags(ct.get("tags") or config.get("tags")),
        "manageable": True,
        "note": None if ip else "no IPv4 address (stopped container with DHCP?)",
    }


async def _qemu(c: httpx.AsyncClient, get_or_none, node: str, vm: dict) -> dict[str, Any]:
    vmid = int(vm["vmid"])
    config = await get_or_none(f"/nodes/{node}/qemu/{vmid}/config") or {}
    cfg_ostype = str(config.get("ostype") or "")
    windows = cfg_ostype.startswith("w")
    agent_enabled = str(config.get("agent") or "0").split(",")[0] in ("1", "enabled=1")
    running = vm.get("status") == "running"

    ip, ostype, note = None, ("windows" if windows else "linux" if cfg_ostype == "l26" else cfg_ostype or None), None
    if running and agent_enabled:
        r = await c.get(f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces")
        if r.status_code == 200:
            ip = _first_ipv4((r.json().get("data") or {}).get("result") or [])
            info = await get_or_none(f"/nodes/{node}/qemu/{vmid}/agent/get-osinfo")
            osinfo = (info or {}).get("result") or {}
            ostype = osinfo.get("id") or ostype
        elif r.status_code == 403:
            note = "no permission for the guest agent (needs VM.GuestAgent.Audit on PVE 9, VM.Monitor on PVE 8)"
        else:
            note = "guest agent not responding (is qemu-guest-agent installed and running?)"
    elif not running:
        note = "VM is not running"
    else:
        note = "QEMU guest agent not enabled in the VM options"

    ip = ip or _static_ip_from_config(config, "ipconfig")
    if ip:
        note = None
    if windows:
        note = "Windows VM: not manageable via SSH/Ansible playbooks"
    elif not ip and not note:
        note = "no IPv4 address reported"
    return {
        "vmid": vmid,
        "type": "qemu",
        "node": node,
        "name": vm.get("name") or config.get("name") or f"vm{vmid}",
        "status": vm.get("status"),
        "ip": ip,
        "ostype": ostype,
        "tags": _tags(vm.get("tags") or config.get("tags")),
        "manageable": not windows,
        "note": note,
    }


async def node_addresses(src: ProxmoxSource, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, str]:
    """Node name -> IP from /cluster/status (also works for single, unclustered nodes)."""
    client, base = _client(src, transport)
    async with client as c:
        try:
            r = await c.get("/cluster/status")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProxmoxError(f"Cannot read node addresses from {base}: {exc}") from exc
        return {e["name"]: e["ip"] for e in r.json()["data"] if e.get("type") == "node" and e.get("ip")}
