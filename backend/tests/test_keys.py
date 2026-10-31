import subprocess

import pytest
from fastapi.testclient import TestClient

from app import keydeploy
from app.keydeploy import DeployResult, install_script
from app.main import app
from app.routers import keys as keys_router

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey controller"


@pytest.mark.parametrize("ensure_sshd", [False, True])
def test_install_script_is_valid_posix_sh(ensure_sshd):
    script = install_script("root", KEY, ensure_sshd)
    assert subprocess.run(["sh", "-n"], input=script, text=True).returncode == 0
    assert "'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey controller'" in script


def test_install_script_quotes_hostile_user():
    script = install_script("x; rm -rf /", KEY)
    assert "U='x; rm -rf /'" in script


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(keys_router, "controller_public_key", lambda: KEY)
    with TestClient(app) as c:
        yield c


def test_deploy_via_ssh_sets_login_user(client, monkeypatch):
    seen = []

    async def fake_ssh(t, password, key):
        seen.append((t.name, t.user, password, key))
        return DeployResult(t.host_id, t.name, True, True, "key added; key login verified")

    monkeypatch.setattr(keys_router, "deploy_via_ssh", fake_ssh)
    h = client.post("/api/hosts", json={"name": "omv-k", "address": "10.8.0.1", "kind": "baremetal"}).json()
    r = client.post("/api/keys/deploy", json={"host_ids": [h["id"]], "method": "ssh", "username": "admin", "password": "pw"})
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["verified"] is True
    assert seen == [("omv-k", "admin", "pw", KEY)]
    host = client.get(f"/api/hosts/{h['id']}").json()
    assert host["ssh_user"] == "admin" and host["last_seen"] and host["last_error"] is None


def test_deploy_via_proxmox_groups_by_node(client, monkeypatch):
    calls = []

    async def fake_addresses(src, transport=None):
        return {"n1": "192.168.0.4", "n2": "192.168.0.5"}

    async def fake_node(address, username, password, targets, key, ensure_sshd, node_port=22):
        calls.append((address, username, sorted(t.vmid for t in targets), ensure_sshd))
        return [DeployResult(t.host_id, t.name, True, True, "ok") for t in targets]

    monkeypatch.setattr(keys_router, "node_addresses", fake_addresses)
    monkeypatch.setattr(keys_router, "deploy_via_proxmox_node", fake_node)

    src = client.post(
        "/api/proxmox/sources", json={"name": "pve-k", "url": "https://pve", "token_id": "a@pam!t", "token_secret": "s"}
    ).json()
    from sqlmodel import Session

    from app.db import engine
    from app.models import Host

    with Session(engine) as s:
        ids = []
        for name, node, vmid in [("ct-a", "n1", 501), ("ct-b", "n1", 502), ("ct-c", "n2", 503)]:
            h = Host(name=name, address=f"10.7.0.{vmid - 500}", source="proxmox", proxmox_source_id=src["id"],
                     proxmox_node=node, proxmox_vmid=vmid)
            s.add(h)
            s.commit()
            ids.append(h.id)
    manual = client.post("/api/hosts", json={"name": "not-a-ct", "address": "10.7.0.9"}).json()

    r = client.post(
        "/api/keys/deploy",
        json={"host_ids": [*ids, manual["id"]], "method": "proxmox", "username": "root", "password": "pw", "ensure_sshd": False},
    ).json()["results"]
    assert sorted(calls) == [("192.168.0.4", "root", [501, 502], False), ("192.168.0.5", "root", [503], False)]
    assert [x["name"] for x in r] == ["ct-a", "ct-b", "ct-c", "not-a-ct"]
    assert r[-1]["ok"] is False and "not an imported Proxmox guest" in r[-1]["message"]


def test_deploy_requires_password(client):
    r = client.post("/api/keys/deploy", json={"host_ids": [1], "method": "ssh", "username": "root", "password": ""})
    assert r.status_code == 422


def test_describe_errors():
    import asyncssh

    assert "login failed" in keydeploy._describe(asyncssh.PermissionDenied("x"))
    assert "cannot connect" in keydeploy._describe(OSError("refused"))


def test_parse_qm_exec():
    from app.keydeploy import parse_qm_exec

    assert parse_qm_exec('{"exitcode": 0, "exited": 1, "out-data": "key added\\n"}') == (0, "key added\n", "")
    assert parse_qm_exec('{"exitcode": 3, "exited": 1, "err-data": "user ghost does not exist"}')[0] == 3
    assert parse_qm_exec('{"exited": 0}')[0] is None
    assert parse_qm_exec("garbage") == (None, "", "garbage")


def test_migration_adds_missing_columns(tmp_path, monkeypatch):
    import sqlite3

    from sqlmodel import create_engine

    from app import db

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE host (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, address VARCHAR NOT NULL)")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{path}"))
    db.init_db()
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(host)")}
    assert {"proxmox_type", "proxmox_vmid", "last_seen"} <= cols
