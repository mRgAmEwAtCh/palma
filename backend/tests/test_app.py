import pytest
from fastapi.testclient import TestClient

from app import runner
from app.main import app
from app.models import Host
from app.playbooks import list_playbooks
from app.proxmox import _first_ipv4, _static_ip_from_config


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_playbook_catalog_lists_starter_playbooks():
    paths = {p.path for p in list_playbooks()}
    assert {"ping.yml", "update.yml", "reboot.yml", "health.yml", "docker_cleanup.yml", "bootstrap.yml"} <= paths
    assert "requirements.yml" not in paths
    ping = next(p for p in list_playbooks() if p.path == "ping.yml")
    assert ping.title == "Ping & gather facts"
    assert "Connectivity check" in ping.description
    assert ping.vars == {}
    by_path = {p.path: p for p in list_playbooks()}
    assert by_path["update.yml"].vars == {"apt_upgrade_mode": "dist", "autoremove": True}
    assert by_path["docker_compose_update.yml"].vars["compose_exclude"] == ["palma"]
    assert by_path["reboot.yml"].vars == {"force_reboot": False, "reboot_serial": 1}


def test_templated_play_vars_are_not_defaults(tmp_path):
    from app.playbooks import _default_vars

    assert _default_vars({"vars": {"a": 1, "b": "{{ a + 1 }}", "c": ["{% if x %}y{% endif %}"]}}) == {"a": 1}


def test_build_inventory_groups_and_vars():
    hosts = [
        Host(id=1, name="web", address="192.168.0.5", tags=["docker", "pve-1"], kind="lxc", vars={"x": 1}),
        Host(id=2, name="omv", address="192.168.0.6", port=2222, ssh_user="admin", kind="baremetal"),
    ]
    inv = runner.build_inventory(hosts)
    web = inv["all"]["hosts"]["web"]
    assert web["ansible_host"] == "192.168.0.5" and web["x"] == 1 and web["ansible_user"] == "root"
    assert inv["all"]["hosts"]["omv"]["ansible_port"] == 2222
    assert inv["all"]["hosts"]["omv"]["ansible_user"] == "admin"
    children = inv["all"]["children"]
    assert set(children["docker"]["hosts"]) == {"web"}
    assert set(children["pve_1"]["hosts"]) == {"web"}
    assert set(children["baremetal"]["hosts"]) == {"omv"}


def test_group_name_sanitizing():
    assert runner.group_name("PVE-1") == "pve_1"
    assert runner.group_name("1st") == "g_1st"


def test_proxmox_ip_parsing():
    assert _first_ipv4([{"name": "lo", "inet": "127.0.0.1/8"}, {"name": "eth0", "inet": "192.168.1.20/24"}]) == "192.168.1.20"
    assert _static_ip_from_config({"net0": "name=eth0,bridge=vmbr0,ip=192.168.1.21/24,gw=192.168.1.1"}, "net") == "192.168.1.21"
    assert _static_ip_from_config({"net0": "name=eth0,bridge=vmbr0,ip=dhcp"}, "net") is None
    assert _static_ip_from_config({"ipconfig0": "ip=192.168.1.22/24,gw=192.168.1.1"}, "ipconfig") == "192.168.1.22"


def test_host_crud(client):
    r = client.post("/api/hosts", json={"name": "pi4", "address": "192.168.1.30", "kind": "baremetal", "tags": [" arm ", "arm", ""]})
    assert r.status_code == 201, r.text
    host = r.json()
    assert host["tags"] == ["arm"]
    assert client.post("/api/hosts", json={"name": "pi4", "address": "x"}).status_code == 409
    r = client.patch(f"/api/hosts/{host['id']}", json={"enabled": False})
    assert r.json()["enabled"] is False
    assert any(h["name"] == "pi4" for h in client.get("/api/hosts").json())
    assert client.delete(f"/api/hosts/{host['id']}").status_code == 204
    assert client.get(f"/api/hosts/{host['id']}").status_code == 404


def test_run_validation(client):
    assert client.post("/api/runs", json={"playbook": "../etc/passwd", "host_ids": [1]}).status_code == 400
    assert client.post("/api/runs", json={"playbook": "ping.yml", "host_ids": []}).status_code == 400
    assert client.post("/api/runs", json={"playbook": "ping.yml", "host_ids": [99999]}).status_code == 400
    assert client.get("/api/playbooks/source", params={"path": "../backend/app/config.py"}).status_code == 404


def test_proxmox_source_secret_not_exposed(client):
    r = client.post(
        "/api/proxmox/sources",
        json={"name": "pve-test", "url": "https://127.0.0.1:1", "token_id": "a@pam!t", "token_secret": "s3cret"},
    )
    assert r.status_code == 201
    assert "token_secret" not in r.json()
    assert "s3cret" not in client.get("/api/proxmox/sources").text
