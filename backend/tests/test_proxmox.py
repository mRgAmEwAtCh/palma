import asyncio

import httpx2
import pytest

from app.models import ProxmoxSource
from app.proxmox import ProxmoxError, _first_ipv4, discover_guests, normalize_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://pve.lan:8006", "https://pve.lan:8006"),
        ("https://pve.lan:8006/", "https://pve.lan:8006"),
        ("https://proxmox.example.de/api2/json", "https://proxmox.example.de"),
        ("https://proxmox.example.de/api2/json/", "https://proxmox.example.de"),
        ("192.168.1.10:8006", "https://192.168.1.10:8006"),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


SRC = ProxmoxSource(id=1, name="pve", url="https://pve.test/api2/json", token_id="u@pam!t", token_secret="x")


def _transport(lxc: list, permissions: dict, status: int = 200, qemu: list | None = None):
    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        assert path.startswith("/api2/json/") and not path.startswith("/api2/json/api2")
        if status != 200:
            return httpx2.Response(status)
        routes = {
            "/api2/json/nodes": [{"node": "n1", "status": "online"}],
            "/api2/json/nodes/n1/lxc": lxc,
            "/api2/json/nodes/n1/lxc/101/config": {"hostname": "web", "ostype": "debian", "net0": "ip=192.168.1.50/24"},
            "/api2/json/nodes/n1/lxc/101/interfaces": [{"name": "eth0", "inet": "192.168.1.51/24"}],
            "/api2/json/access/permissions": permissions,
            "/api2/json/nodes/n1/qemu": qemu or [],
            "/api2/json/nodes/n1/qemu/150/config": {"ostype": "l26", "agent": "1", "name": "haos"},
            "/api2/json/nodes/n1/qemu/151/config": {"ostype": "l26", "ipconfig0": "ip=192.168.1.60/24,gw=192.168.1.1"},
            "/api2/json/nodes/n1/qemu/152/config": {"ostype": "l26", "agent": "1"},
            "/api2/json/nodes/n1/qemu/200/config": {"ostype": "win11"},
            "/api2/json/nodes/n1/qemu/150/agent/network-get-interfaces": {"result": [
                {"name": "lo", "ip-addresses": [{"ip-address-type": "ipv4", "ip-address": "127.0.0.1"}]},
                {"name": "docker0", "ip-addresses": [{"ip-address-type": "ipv4", "ip-address": "172.30.32.1"}]},
                {"name": "enp0s18", "ip-addresses": [
                    {"ip-address-type": "ipv6", "ip-address": "fe80::1"},
                    {"ip-address-type": "ipv4", "ip-address": "192.168.1.150"}]},
            ]},
            "/api2/json/nodes/n1/qemu/150/agent/get-osinfo": {"result": {"id": "haos", "pretty-name": "Home Assistant OS"}},
        }
        if path == "/api2/json/nodes/n1/qemu/152/agent/network-get-interfaces":
            return httpx2.Response(500, json={"data": None})
        return httpx2.Response(200, json={"data": routes[path]})

    return httpx2.MockTransport(handler)


def test_discover_finds_containers():
    t = _transport([{"vmid": 101, "name": "web", "status": "running", "tags": "docker;prod"}], {"/": {"VM.Audit": 1}})
    found = asyncio.run(discover_guests(SRC, transport=t))
    assert found["warning"] is None and found["nodes"] == ["n1"]
    ct = found["guests"][0]
    assert ct["type"] == "lxc" and ct["manageable"] and ct["note"] is None
    assert ct["ip"] == "192.168.1.51" and ct["ostype"] == "debian" and ct["tags"] == ["docker", "prod"]


def test_discover_finds_vms():
    qemu = [
        {"vmid": 150, "name": "haos", "status": "running", "tags": "smart-home"},
        {"vmid": 151, "name": "cloudinit-vm", "status": "stopped"},
        {"vmid": 152, "name": "no-agent-running", "status": "running"},
        {"vmid": 200, "name": "windows-11", "status": "stopped"},
        {"vmid": 9000, "name": "tpl", "status": "stopped", "template": 1},
    ]
    found = asyncio.run(discover_guests(SRC, transport=_transport([], {"/": {"VM.Audit": 1}}, qemu=qemu)))
    vms = {g["vmid"]: g for g in found["guests"]}
    assert set(vms) == {150, 151, 152, 200}  # templates are skipped
    assert vms[150]["type"] == "qemu" and vms[150]["ip"] == "192.168.1.150" and vms[150]["ostype"] == "haos"
    assert vms[150]["tags"] == ["smart-home"] and vms[150]["note"] is None
    assert vms[151]["ip"] == "192.168.1.60" and vms[151]["note"] is None  # cloud-init static IP
    assert vms[152]["ip"] is None and "guest agent not responding" in vms[152]["note"]
    assert vms[200]["manageable"] is False and "Windows" in vms[200]["note"]


def test_first_ipv4_skips_bridges_and_link_local():
    ifaces = [{"name": "eth0", "inet": "169.254.1.1/16"}, {"name": "br-123", "inet": "172.18.0.1/16"},
              {"name": "eth1", "inet": "192.168.1.9/24"}]
    assert _first_ipv4(ifaces) == "192.168.1.9"


def test_discover_explains_missing_permissions():
    found = asyncio.run(discover_guests(SRC, transport=_transport([], {})))
    assert found["guests"] == [] and found["nodes"] == ["n1"]
    assert "VM.Audit" in found["warning"] and "pveum acl modify / --tokens 'u@pam!t'" in found["warning"]


def test_discover_empty_with_permissions():
    found = asyncio.run(discover_guests(SRC, transport=_transport([], {"/": {"VM.Audit": 1}})))
    assert found["warning"] == "No containers or VMs found on node(s): n1."


def test_discover_http_error():
    with pytest.raises(ProxmoxError, match="HTTP 501"):
        asyncio.run(discover_guests(SRC, transport=_transport([], {}, status=501)))


def test_import_links_manual_host_with_same_ip(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routers import proxmox as proxmox_router

    async def fake_discover(src, transport=None):
        return {
            "nodes": ["n1"],
            "warning": None,
            "guests": [
                {"vmid": 301, "type": "lxc", "node": "n1", "name": "linkme", "status": "running", "ip": "10.9.9.1",
                 "ostype": "debian", "tags": [], "manageable": True, "note": None},
                {"vmid": 302, "type": "qemu", "node": "n1", "name": "fresh", "status": "running", "ip": "10.9.9.2",
                 "ostype": "debian", "tags": ["x"], "manageable": True, "note": None},
                {"vmid": 303, "type": "qemu", "node": "n1", "name": "win", "status": "stopped", "ip": None,
                 "ostype": "windows", "tags": [], "manageable": False, "note": "Windows VM: not manageable"},
            ],
        }

    monkeypatch.setattr(proxmox_router, "discover_guests", fake_discover)
    with TestClient(app) as c:
        manual = c.post("/api/hosts", json={"name": "my-manual", "address": "10.9.9.1", "tags": ["mine"]}).json()
        src = c.post(
            "/api/proxmox/sources",
            json={"name": "pve-link", "url": "pve.test:8006/api2/json", "token_id": "a@pam!t", "token_secret": "s"},
        ).json()
        assert src["url"] == "https://pve.test:8006"

        found = c.get(f"/api/proxmox/sources/{src['id']}/discover").json()
        assert {g["vmid"]: g["host_id"] for g in found["guests"]} == {301: manual["id"], 302: None, 303: None}

        r = c.post(f"/api/proxmox/sources/{src['id']}/import", json={"vmids": [301, 302, 303]}).json()
        assert r["created"] == 1 and r["updated"] == 1
        assert r["skipped"] == [{"vmid": 303, "name": "win", "reason": "Windows VM: not manageable"}]
        vm = next(h for h in c.get("/api/hosts").json() if h["name"] == "fresh")
        assert vm["kind"] == "vm" and vm["proxmox_type"] == "qemu"

        linked = c.get(f"/api/hosts/{manual['id']}").json()
        assert linked["name"] == "my-manual" and linked["source"] == "proxmox" and linked["proxmox_vmid"] == 301
        assert linked["proxmox_type"] == "lxc"
        assert set(linked["tags"]) == {"mine", "proxmox", "pve-link"}

        again = c.post(f"/api/proxmox/sources/{src['id']}/import", json={"vmids": [301, 302]}).json()
        assert again["created"] == 0 and again["updated"] == 2
