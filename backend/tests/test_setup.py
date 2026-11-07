import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import Host, PlaybookRepository, ProxmoxSource, Run, Schedule, SetupState
from app import repositories, runner
from app.proxmox import ProxmoxError
from app.routers import proxmox, setup


@pytest.fixture()
def setup_client(tmp_path, monkeypatch):
    settings = get_settings()
    playbooks = tmp_path / "playbooks"
    shutil.copytree(settings.playbooks_dir, playbooks)
    bundled = tmp_path / "bundled"
    shutil.copytree(settings.playbooks_dir, bundled)
    for name, value in {
        "data_dir": tmp_path,
        "playbooks_dir": playbooks,
        "ssh_key_path": str(tmp_path / "ssh" / "id_ed25519"),
        "auth_disabled": False,
        "oidc_issuer": "",
        "oidc_client_id": "",
        "admin_password": "",
        "admin_password_hash": "",
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(repositories, "BUNDLED_PLAYBOOKS", bundled)
    engine = create_engine(f"sqlite:///{tmp_path / 'setup.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def sessions():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    try:
        with TestClient(app) as client:
            yield client, settings, engine
    finally:
        app.dependency_overrides.pop(get_session)
        engine.dispose()


def claim(client):
    response = client.post("/setup/account", json={"username": "owner", "password": "a-long-test-password"})
    assert response.status_code == 201, response.text


def test_fresh_start_account_and_access_control(setup_client):
    client, settings, _ = setup_client
    assert client.get("/healthz").status_code == 200
    assert client.get("/setup/status").json() == {
        "required": True, "needs_account": True, "default_repository": setup.DEFAULT_REPOSITORY,
    }
    assert client.get("/api/hosts").status_code == 401
    assert client.get("/setup/details").status_code == 401
    assert client.post("/setup/ssh-key").status_code == 401
    assert client.post("/setup/complete").status_code == 401
    assert client.post("/auth/local", json={"username": "admin", "password": ""}).status_code == 401
    assert client.post("/setup/account", json={"password": "short"}).status_code == 422
    assert client.post("/setup/account", json={"password": "a-long-test-password"}, headers={"Origin": "https://other.example"}).status_code == 403
    claim(client)
    assert client.get("/api/me").json()["name"] == "owner"
    assert client.get("/setup/status").json()["needs_account"] is False
    stored = json.loads((settings.data_dir / "admin.json").read_text())
    assert stored["password_hash"] != "a-long-test-password"
    assert "a-long-test-password" not in (settings.data_dir / "admin.json").read_text()
    assert client.post("/setup/account", json={"password": "another-long-password"}).status_code == 409
    client.get("/auth/logout")
    assert client.post("/auth/local", json={"username": "owner", "password": "wrong"}).status_code == 401
    assert client.post("/auth/local", json={"username": "owner", "password": "a-long-test-password"}).status_code == 200


def test_key_and_default_repository_optional_proxmox_persist(setup_client, monkeypatch):
    client, settings, engine = setup_client
    claim(client)
    assert client.post("/setup/complete").status_code == 400
    result = client.post("/setup/ssh-key")
    assert result.status_code == 200, result.text
    public_key = result.json()["ssh_public_key"]
    assert public_key.startswith("ssh-ed25519 ")
    private = Path(settings.ssh_key_path)
    content = private.read_bytes()
    assert private.stat().st_mode & 0o777 == 0o600
    assert client.post("/setup/ssh-key").json()["ssh_public_key"] == public_key
    assert private.read_bytes() == content
    original_run = subprocess.run

    def no_clone(command, **kwargs):
        assert command[0] != "git", "The bundled default must not require Git or network access"
        return original_run(command, **kwargs)

    monkeypatch.setattr(setup.subprocess, "run", no_clone)
    assert client.post("/setup/repository", json={}).status_code == 200
    sources = client.get("/api/system").json()["playbook_repositories"]
    assert any(source["url"] == setup.DEFAULT_REPOSITORY and source["folder"] == "sources/palma" for source in sources)
    assert client.post("/setup/complete").status_code == 200
    assert client.get("/setup/status").json()["required"] is False
    with Session(engine) as s:
        assert s.get(SetupState, 1).completed is True
        assert not s.exec(select(ProxmoxSource)).all()
    assert client.post("/setup/repository", json={}).status_code == 200
    with TestClient(app) as reopened:
        assert reopened.get("/setup/status").json()["required"] is False


def test_settings_reload_preserves_account_and_session_secret(setup_client, monkeypatch):
    client, settings, _ = setup_client
    claim(client)
    monkeypatch.setenv("DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    monkeypatch.setenv("SESSION_SECRET", "")
    first = get_settings.__wrapped__()
    second = get_settings.__wrapped__()
    assert first.admin_username == "owner"
    assert first.admin_password_hash == settings.admin_password_hash
    assert not first.needs_account
    assert first.session_secret == second.session_secret
    assert len(first.session_secret) == 64
    assert (settings.data_dir / "session-secret").stat().st_mode & 0o777 == 0o600


def test_existing_environment_login_is_preserved(setup_client, monkeypatch):
    client, settings, _ = setup_client
    monkeypatch.setattr(settings, "admin_password", "existing-password")
    monkeypatch.setattr(settings, "admin_username", "existing-admin")
    assert not client.get("/setup/status").json()["needs_account"]
    assert client.post("/setup/account", json={"password": "a-long-test-password"}).status_code == 409
    assert client.post("/auth/local", json={"username": "existing-admin", "password": "existing-password"}).status_code == 200


def test_provided_private_key_is_kept_and_bad_public_key_rejected(setup_client):
    client, settings, _ = setup_client
    claim(client)
    key = Path(settings.ssh_key_path)
    key.parent.mkdir()
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key)], check=True, capture_output=True)
    original = key.read_bytes()
    pub = Path(f"{key}.pub")
    pub.unlink()
    assert client.post("/setup/ssh-key").status_code == 200
    assert key.read_bytes() == original
    pub.write_text("ssh-ed25519 invalid")
    assert client.post("/setup/ssh-key").status_code == 400
    key.write_text("invalid private key")
    assert client.post("/setup/ssh-key").status_code == 400


@pytest.mark.parametrize("body", [
    {"url": "file:///tmp/repo"},
    {"url": "https://user:password@example.com/repo"},
    {"url": "https://example.com/repo?token=secret"},
    {"path": "../outside"},
    {"path": "/absolute"},
    {"path": r"..\outside"},
    {"ref": "--upload-pack=bad"},
])
def test_repository_rejects_invalid_inputs(setup_client, body):
    client, _, _ = setup_client
    claim(client)
    assert client.post("/setup/repository", json=body).status_code == 400


@pytest.fixture()
def local_repository(tmp_path, monkeypatch):
    repo = tmp_path / "upstream"
    repo.mkdir()
    (repo / "automation").mkdir()
    (repo / "automation" / "custom.yml").write_text("- hosts: all\n  tasks: []\n")
    (repo / "automation" / "vars").mkdir()
    (repo / "automation" / "vars" / "example.yml").write_text("example: true\n")
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture"],
        check=True, capture_output=True,
    )
    original_run = subprocess.run

    def clone_local(command, **kwargs):
        if command[:2] == ["git", "clone"]:
            assert command[-2] in {"https://example.invalid/repo.git", "http://example.invalid/repo.git"}
            command = [*command[:-2], str(repo), command[-1]]
        return original_run(command, **kwargs)

    monkeypatch.setattr(setup.subprocess, "run", clone_local)
    return repo


def test_custom_repository_snapshot_is_additive(setup_client, local_repository):
    client, settings, _ = setup_client
    claim(client)
    root = settings.playbooks_dir
    response = client.post("/setup/repository", json={
        "name": "lab", "url": "https://example.invalid/repo.git", "ref": "main", "path": "automation",
    })
    assert response.status_code == 200, response.text
    paths = {p["path"] for p in client.get("/api/playbooks").json()}
    assert {"ping.yml", "sources/lab/custom.yml"} <= paths
    assert (root / "sources" / "lab" / "vars" / "example.yml").exists()
    assert not (root / ".git").exists()
    assert any(source["ref"] == "main" for source in client.get("/setup/details").json()["repositories"])


def test_failed_repository_import_restores_previous_files(setup_client, local_repository, monkeypatch):
    client, settings, _ = setup_client
    claim(client)
    old = (settings.playbooks_dir / "ping.yml").read_bytes()

    def fail_move(*args, **kwargs):
        raise OSError("simulated import failure")

    monkeypatch.setattr(repositories.shutil, "copytree", fail_move)
    response = client.post("/setup/repository", json={"url": "https://example.invalid/repo.git", "path": "automation"})
    assert response.status_code == 500
    assert (settings.playbooks_dir / "ping.yml").read_bytes() == old
    assert client.get("/setup/details").json()["repository_url"] == ""


def test_bad_repository_folder_does_not_replace_playbooks(setup_client, local_repository):
    client, settings, _ = setup_client
    claim(client)
    response = client.post("/setup/repository", json={"url": "https://example.invalid/repo.git", "path": "missing"})
    assert response.status_code == 400
    assert (settings.playbooks_dir / "ping.yml").exists()


def test_repository_clone_failure_is_explicit(setup_client, monkeypatch):
    client, settings, _ = setup_client
    claim(client)

    def fail_clone(*args, **kwargs):
        raise subprocess.CalledProcessError(128, "git clone")

    monkeypatch.setattr(setup.subprocess, "run", fail_clone)
    response = client.post("/setup/repository", json={"url": "https://example.invalid/missing.git"})
    assert response.status_code == 502
    assert (settings.playbooks_dir / "ping.yml").exists()
    assert client.get("/setup/details").json()["repository_url"] == ""


def test_repository_requires_catalog_compatible_files(setup_client, local_repository):
    client, settings, _ = setup_client
    claim(client)
    source = local_repository / "automation"
    (source / "custom.yml").rename(source / "custom.yxxml")
    subprocess.run(["git", "-C", str(local_repository), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(local_repository), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "unsupported extension"],
        check=True, capture_output=True,
    )
    response = client.post("/setup/repository", json={"url": "https://example.invalid/repo.git", "path": "automation"})
    assert response.status_code == 400
    assert (settings.playbooks_dir / "ping.yml").exists()


def test_proxmox_test_does_not_store_token(setup_client, monkeypatch):
    client, _, engine = setup_client
    claim(client)

    async def discover(src):
        assert src.token_secret == "test-secret"
        return {"nodes": ["pve"], "guests": [], "warning": "No guests found"}

    monkeypatch.setattr(proxmox, "discover_guests", discover)
    body = {"name": "pve", "url": "https://pve.invalid:8006", "token_id": "palma@pve!palma", "token_secret": "test-secret"}
    response = client.post("/api/proxmox/test", json=body)
    assert response.status_code == 200
    assert "test-secret" not in response.text
    with Session(engine) as s:
        assert not s.exec(select(ProxmoxSource)).all()

    async def fail(src):
        raise ProxmoxError("Authentication failed")

    monkeypatch.setattr(proxmox, "discover_guests", fail)
    assert client.post("/api/proxmox/test", json=body).status_code == 502


def add_git(client, name="lab", url="https://example.invalid/repo.git", ref="main"):
    response = client.post("/api/playbooks/repositories", json={
        "name": name, "url": url, "ref": ref, "path": "automation",
    })
    assert response.status_code == 201, response.text
    return response.json()


def commit_repo(repo, message="update"):
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", message],
        check=True, capture_output=True,
    )


def test_multiple_git_and_local_sources_duplicate_names(setup_client, local_repository):
    client, settings, engine = setup_client
    claim(client)
    first = add_git(client, "first")
    second = add_git(client, "second", "http://example.invalid/repo.git")
    root = settings.playbooks_dir
    (root / "custom.yml").write_text("- name: Local root\n  hosts: all\n  tasks: []\n")
    local = root / "sources" / "on-disk"
    local.mkdir()
    (local / "custom.yml").write_text("- name: On disk\n  hosts: all\n  tasks: []\n")
    (local / "tasks").mkdir()
    (local / "tasks" / "not-a-play.yml").write_text("- hosts: all\n")
    catalog = {p["path"]: p for p in client.get("/api/playbooks").json()}
    assert {"custom.yml", "sources/first/custom.yml", "sources/second/custom.yml", "sources/on-disk/custom.yml"} <= catalog.keys()
    assert catalog["sources/first/custom.yml"]["source"] == "first"
    assert catalog["custom.yml"]["source"] == "local"
    assert "sources/on-disk/tasks/not-a-play.yml" not in catalog
    sources = client.get("/api/playbooks/repositories").json()
    assert any(source["name"] == "on-disk" and source["kind"] == "local" for source in sources)
    # Re-adding the same URL/ref/path is idempotent.
    assert add_git(client, "ignored")["id"] == first["id"]
    with Session(engine) as s:
        assert len(s.exec(select(PlaybookRepository)).all()) == 2
    assert first["id"] != second["id"]
    assert client.post("/api/playbooks/repositories", json={
        "name": "on-disk", "url": "http://example.invalid/repo.git", "ref": "", "path": "automation",
    }).status_code == 409
    assert client.get("/setup/details").json()["repositories"]


def test_local_only_can_complete_setup(setup_client):
    client, settings, _ = setup_client
    claim(client)
    assert client.post("/setup/ssh-key").status_code == 200
    assert client.post("/setup/complete").status_code == 200
    for p in settings.playbooks_dir.iterdir():
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
    assert client.post("/setup/complete").status_code == 400


def test_pull_updates_only_selected_source_and_backs_up_edits(setup_client, local_repository):
    client, settings, _ = setup_client
    claim(client)
    first = add_git(client, "first")
    second = add_git(client, "second", "http://example.invalid/repo.git")
    root = settings.playbooks_dir
    first_dir = root / first["folder"]
    second_content = (root / second["folder"] / "custom.yml").read_bytes()
    local_content = (root / "ping.yml").read_bytes()
    (first_dir / "custom.yml").write_text("- name: Edited locally\n  hosts: all\n  tasks: []\n")
    (first_dir / "removed.yml").write_text("- hosts: all\n  tasks: []\n")
    upstream = local_repository / "automation"
    (upstream / "custom.yml").write_text("- name: Latest\n  hosts: all\n  tasks: []\n")
    (upstream / "new.yml").write_text("- name: New\n  hosts: all\n  tasks: []\n")
    (upstream / "vars" / "example.yml").write_text("example: updated\n")
    commit_repo(local_repository)
    response = client.post(f"/api/playbooks/repositories/{first['id']}/pull")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["folder"] == first["folder"]
    assert not result["legacy_migrated"]
    backup = settings.data_dir / result["backup"]
    assert "Edited locally" in (backup / "custom.yml").read_text()
    assert (backup / "removed.yml").exists()
    assert "Latest" in (first_dir / "custom.yml").read_text()
    assert (first_dir / "new.yml").exists()
    assert not (first_dir / "removed.yml").exists()
    assert (first_dir / "vars" / "example.yml").read_text() == "example: updated\n"
    assert (root / second["folder"] / "custom.yml").read_bytes() == second_content
    assert (root / "ping.yml").read_bytes() == local_content
    assert client.get("/api/playbooks/source", params={"path": f"{first['folder']}/custom.yml"}).status_code == 200


def test_failed_pull_keeps_catalog_and_edits(setup_client, local_repository, monkeypatch):
    client, settings, _ = setup_client
    claim(client)
    record = add_git(client)
    path = settings.playbooks_dir / record["folder"] / "custom.yml"
    old = path.read_bytes()

    def fail_clone(*args, **kwargs):
        raise subprocess.CalledProcessError(128, "git clone")

    monkeypatch.setattr(repositories.subprocess, "run", fail_clone)
    assert client.post(f"/api/playbooks/repositories/{record['id']}/pull").status_code == 502
    assert path.read_bytes() == old
    assert client.post("/api/playbooks/repositories/99999/pull").status_code == 404


def test_pull_swap_failure_restores_source(setup_client, local_repository, monkeypatch):
    client, settings, _ = setup_client
    claim(client)
    record = add_git(client)
    old = (settings.playbooks_dir / record["folder"] / "custom.yml").read_bytes()
    original = Path.rename

    def fail_install(path, destination):
        if path.name.startswith(".import-"):
            raise OSError("simulated swap failure")
        return original(path, destination)

    monkeypatch.setattr(Path, "rename", fail_install)
    response = client.post(f"/api/playbooks/repositories/{record['id']}/pull")
    assert response.status_code == 500, response.text
    assert (settings.playbooks_dir / record["folder"] / "custom.yml").read_bytes() == old
    assert not list((settings.playbooks_dir / "sources").glob(".previous-*"))


def test_pull_blocks_active_runs_and_source_schedules(setup_client, local_repository):
    client, _, engine = setup_client
    claim(client)
    record = add_git(client)
    url = f"/api/playbooks/repositories/{record['id']}/pull"
    with Session(engine) as s:
        run = Run(playbook="ping.yml", status="running")
        s.add(run)
        s.commit()
        s.refresh(run)
        run_id = run.id
    assert client.post(url).status_code == 409
    with Session(engine) as s:
        run = s.get(Run, run_id)
        run.status = "successful"
        schedule = Schedule(name="repo schedule", cron="0 * * * *", playbook=f"{record['folder']}/custom.yml")
        s.add(run)
        s.add(schedule)
        s.commit()
        s.refresh(schedule)
        schedule_id = schedule.id
    assert client.post(url).status_code == 409
    with Session(engine) as s:
        schedule = s.get(Schedule, schedule_id)
        schedule.enabled = False
        s.add(schedule)
        s.commit()
    assert client.post(url).status_code == 200
    assert client.post("/api/schedules", json={
        "name": "namespaced", "cron": "0 * * * *", "playbook": f"{record['folder']}/custom.yml",
    }).status_code == 201


def test_source_editor_and_runner_use_relative_includes(setup_client, local_repository, monkeypatch):
    client, settings, engine = setup_client
    claim(client)
    record = add_git(client)
    folder = settings.playbooks_dir / record["folder"]
    (folder / "tasks").mkdir()
    (folder / "tasks" / "hello.yml").write_text("- ansible.builtin.debug:\n    msg: '{{ example }}'\n")
    content = "- name: Relative\n  hosts: all\n  vars_files:\n    - vars/example.yml\n  tasks:\n    - ansible.builtin.import_tasks: tasks/hello.yml\n"
    name = f"{record['folder']}/custom.yml"
    response = client.put("/api/playbooks/file", json={"name": name, "content": content})
    assert response.status_code == 200, response.text
    assert response.json()["validation"]["valid"]
    assert list((settings.data_dir / "playbook-history" / name).iterdir())
    assert client.post("/api/playbooks/validate", json={"name": name, "content": content}).json()["valid"]

    captured = {}

    original_run = runner.ansible_runner.run

    def capture_run(**kwargs):
        captured.update(kwargs)
        return original_run(**kwargs)

    monkeypatch.setattr(runner, "engine", engine)
    monkeypatch.setattr(runner.ansible_runner, "run", capture_run)
    monkeypatch.setattr(runner, "start", lambda run_id: None)
    host = client.post("/api/hosts", json={
        "name": "relative-host", "address": "127.0.0.1", "vars": {"ansible_connection": "local"},
    }).json()
    run = client.post("/api/runs", json={"playbook": name, "host_ids": [host["id"]]})
    assert run.status_code == 201, run.text
    runner._execute(run.json()["id"])
    assert Path(captured["project_dir"]) == folder
    assert captured["playbook"] == "custom.yml"
    assert client.get(f"/api/runs/{run.json()['id']}").json()["status"] == "successful"
    assert client.delete("/api/playbooks/file", params={"name": name}).status_code == 204
    assert not (folder / "custom.yml").exists()
    assert (settings.playbooks_dir / "ping.yml").exists()


@pytest.mark.parametrize("name", ["sources/../ping.yml", "sources/missing/a.yml", "sources/lab/tasks/a.yml", r"sources\lab\a.yml"])
def test_source_editor_rejects_traversal(setup_client, name):
    client, _, _ = setup_client
    claim(client)
    assert client.put("/api/playbooks/file", json={"name": name, "content": "- hosts: all\n", "create": True}).status_code == 400
    assert client.post("/api/playbooks/validate", json={"name": name, "content": "- hosts: all\n"}).status_code == 400


def test_legacy_source_pull_preserves_root_files(setup_client, local_repository):
    client, settings, engine = setup_client
    claim(client)
    with Session(engine) as s:
        s.add(SetupState(repository_url="https://example.invalid/repo.git", repository_ref="main", repository_path="automation"))
        s.commit()
    sources = client.get("/api/playbooks/repositories").json()
    record = next(source for source in sources if source["kind"] == "git")
    root_content = (settings.playbooks_dir / "ping.yml").read_bytes()
    response = client.post(f"/api/playbooks/repositories/{record['id']}/pull")
    assert response.status_code == 200, response.text
    assert response.json()["legacy_migrated"]
    assert (settings.playbooks_dir / "ping.yml").read_bytes() == root_content
    assert (settings.playbooks_dir / response.json()["folder"] / "custom.yml").exists()


def test_bundled_source_can_pull_without_image_update(setup_client, local_repository, monkeypatch):
    client, settings, _ = setup_client
    claim(client)
    marker = settings.playbooks_dir / "sources" / "palma"
    shutil.copytree(settings.playbooks_dir / "vars", marker / "vars")
    (marker / "ping.yml").write_text("- name: Bundled\n  hosts: all\n  tasks: []\n")
    (marker / ".palma-bundled").touch()
    source = next(p for p in client.get("/api/playbooks/repositories").json() if p["name"] == "palma")
    original = subprocess.run

    def clone_bundle(command, **kwargs):
        if command[:2] == ["git", "clone"]:
            assert command[-2] == repositories.DEFAULT_REPOSITORY
            command = [*command[:-2], "https://example.invalid/repo.git", command[-1]]
        return original(command, **kwargs)

    (local_repository / "automation").rename(local_repository / "playbooks")
    commit_repo(local_repository)
    monkeypatch.setattr(repositories.subprocess, "run", clone_bundle)
    response = client.post(f"/api/playbooks/repositories/{source['id']}/pull")
    assert response.status_code == 200, response.text
    assert (marker / "custom.yml").exists()
    assert not (marker / "ping.yml").exists()
    assert (settings.playbooks_dir / "ping.yml").exists()


def test_local_source_symlinks_are_not_listed_or_editable(setup_client):
    client, settings, _ = setup_client
    claim(client)
    sources = settings.playbooks_dir / "sources"
    sources.mkdir()
    (sources / "linked").symlink_to(settings.playbooks_dir, target_is_directory=True)
    assert not any(p["path"].startswith("sources/linked/") for p in client.get("/api/playbooks").json())
    assert client.put("/api/playbooks/file", json={
        "name": "sources/linked/ping.yml", "content": "- hosts: all\n",
    }).status_code == 400
