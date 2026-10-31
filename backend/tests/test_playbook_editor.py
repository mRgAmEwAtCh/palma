import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.playbook_editor import validate

VALID = """---
# Says hello.
# Extra vars: greeting (default hello)
- name: Hello
  hosts: all
  gather_facts: false
  vars:
    greeting: hello
  tasks:
    - name: Greet
      ansible.builtin.debug:
        msg: "{{ greeting }}"
"""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    settings = get_settings()
    pb = tmp_path / "playbooks"
    shutil.copytree(Path(__file__).resolve().parents[2] / "playbooks", pb, ignore=shutil.ignore_patterns("sssd_vars.yml"))
    monkeypatch.setattr(settings, "playbooks_dir", pb)
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    with TestClient(app) as c:
        yield c, pb, tmp_path / "data"


def test_validate_reports_line_numbers():
    r = validate("- name: t\n  hosts: all\n  tasks:\n    - name: x\n     debug: msg=hi\n")
    assert not r.valid and r.errors[0].source == "yaml" and r.errors[0].line == 5
    r = validate("- name: t\n  hosts: all\n  tasks:\n    - name: x\n      ansible.builtin.nope:\n")
    assert not r.valid and r.errors[0].source == "ansible" and r.errors[0].line == 4
    assert "couldn't resolve module/action" in r.errors[0].message


def test_validate_structure_and_warnings():
    assert "list of plays" in validate("name: x\nhosts: all\n").errors[0].message
    assert "no 'hosts'" in validate("- name: x\n  tasks: []\n").errors[0].message
    assert "empty" in validate("").errors[0].message
    r = validate("- hosts: web\n  tasks:\n    - ansible.builtin.ping:\n")
    assert r.valid and any("targets 'web'" in w.message for w in r.warnings)


def test_validate_accepts_vault_tags():
    content = "- name: t\n  hosts: all\n  vars:\n    s: !vault |\n      $ANSIBLE_VAULT;1.1;AES256\n      6162\n  tasks:\n    - ansible.builtin.ping:\n"
    assert validate(content).valid


def test_create_edit_delete_with_history(client):
    c, pb, data = client
    r = c.put("/api/playbooks/file", json={"name": "hello.yml", "content": VALID, "create": True})
    assert r.status_code == 200, r.text
    listed = {p["path"]: p for p in c.get("/api/playbooks").json()}
    assert listed["hello.yml"]["title"] == "Hello" and listed["hello.yml"]["vars"] == {"greeting": "hello"}
    assert "Says hello." in listed["hello.yml"]["description"]

    assert c.put("/api/playbooks/file", json={"name": "hello.yml", "content": VALID, "create": True}).status_code == 400

    edited = VALID.replace("greeting: hello", "greeting: hi")
    assert c.put("/api/playbooks/file", json={"name": "hello.yml", "content": edited}).status_code == 200
    assert "greeting: hi" in c.get("/api/playbooks/source", params={"path": "hello.yml"}).text
    history = list((data / "playbook-history" / "hello.yml").iterdir())
    assert len(history) == 1 and "greeting: hello" in history[0].read_text()

    assert c.delete("/api/playbooks/file", params={"name": "hello.yml"}).status_code == 204
    assert not (pb / "hello.yml").exists()
    assert any(p.name.endswith("-deleted.yml") for p in (data / "playbook-history" / "hello.yml").iterdir())


def test_invalid_content_is_not_saved(client):
    c, pb, _ = client
    original = (pb / "ping.yml").read_text()
    r = c.put("/api/playbooks/file", json={"name": "ping.yml", "content": "- name: broken\n  tasks: []\n"})
    assert r.status_code == 422
    assert r.json()["detail"]["validation"]["errors"][0]["source"] == "structure"
    assert (pb / "ping.yml").read_text() == original


@pytest.mark.parametrize("name", ["../evil.yml", "tasks/x.yml", "requirements.yml", ".hidden.yml", "noext", "a b.yml"])
def test_rejects_bad_names(client, name):
    c, _, _ = client
    r = c.put("/api/playbooks/file", json={"name": name, "content": VALID, "create": True})
    assert r.status_code == 400


def test_edit_requires_existing_file(client):
    c, _, _ = client
    assert c.put("/api/playbooks/file", json={"name": "missing.yml", "content": VALID}).status_code == 404
    assert c.delete("/api/playbooks/file", params={"name": "missing.yml"}).status_code == 404
