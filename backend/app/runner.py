"""Executes playbooks with ansible-runner in background threads and records results."""

import logging
import re
import shutil
import threading
from pathlib import Path
from typing import Any

import ansible_runner
from sqlmodel import Session, select

from .config import get_settings
from .db import engine
from .models import Host, Run, utcnow

log = logging.getLogger(__name__)
settings = get_settings()

_cancel_requested: set[int] = set()
_active: dict[int, threading.Thread] = {}
_lock = threading.Lock()

TERMINAL_STATES = {"successful", "failed", "canceled", "error", "timeout"}


def group_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", value.strip().lower())
    return name if name and not name[0].isdigit() else f"g_{name}"


def build_inventory(hosts: list[Host]) -> dict[str, Any]:
    all_hosts: dict[str, dict[str, Any]] = {}
    children: dict[str, dict[str, Any]] = {}
    for h in hosts:
        hv: dict[str, Any] = {
            "ansible_host": h.address,
            "ansible_port": h.port,
            "ansible_user": h.ssh_user or settings.default_ssh_user,
        }
        if settings.ssh_key_path:
            hv["ansible_ssh_private_key_file"] = settings.ssh_key_path
        hv.update(h.vars or {})
        all_hosts[h.name] = hv
        for g in {*(h.tags or []), h.kind}:
            if g:
                children.setdefault(group_name(g), {"hosts": {}})["hosts"][h.name] = {}
    return {"all": {"hosts": all_hosts, "children": children}}


def log_path(run_id: int) -> Path:
    return settings.runs_dir / str(run_id) / "output.log"


def is_active(run_id: int) -> bool:
    with _lock:
        t = _active.get(run_id)
        return bool(t and t.is_alive())


def cancel(run_id: int) -> None:
    _cancel_requested.add(run_id)


def recover_interrupted_runs() -> None:
    """Marks runs left in a non-terminal state (e.g. after a restart) as errored."""
    with Session(engine) as s:
        for run in s.exec(select(Run).where(Run.status.in_(["pending", "running"]))):
            run.status = "error"
            run.finished_at = utcnow()
            s.add(run)
        s.commit()


def start(run_id: int) -> None:
    t = threading.Thread(target=_execute, args=(run_id,), name=f"run-{run_id}", daemon=True)
    with _lock:
        _active[run_id] = t
    t.start()


def create_and_start(
    s: Session,
    playbook: str,
    hosts: list[Host],
    *,
    check_mode: bool = False,
    extra_vars: dict[str, Any] | None = None,
    triggered_by: str | None = None,
    schedule_id: int | None = None,
) -> Run:
    run = Run(
        playbook=playbook,
        check_mode=check_mode,
        extra_vars=extra_vars or {},
        host_ids=sorted({h.id for h in hosts}),
        host_names=sorted(h.name for h in hosts),
        triggered_by=triggered_by,
        schedule_id=schedule_id,
    )
    s.add(run)
    s.commit()
    s.refresh(run)
    start(run.id)
    return run


def _apply_host_results(
    s: Session, hosts: list[Host], stats: dict, facts: dict, errors: dict, statuses: dict | None = None
) -> None:
    processed = set((stats or {}).get("processed", {}))
    dark = set((stats or {}).get("dark", {}))
    now = utcnow()
    for h in hosts:
        if h.name in facts:
            f = facts[h.name]
            h.os_family = f.get("ansible_os_family") or h.os_family
            h.os_name = f.get("ansible_distribution") or h.os_name
            h.os_version = f.get("ansible_distribution_version") or h.os_version
        if statuses and h.name in statuses:
            h.health = statuses[h.name]
            h.health_checked_at = now
        if h.name in dark:
            h.last_error = errors.get(h.name, "unreachable")
        elif h.name in processed:
            h.last_seen = now
            h.last_error = None
        s.add(h)


def _execute(run_id: int) -> None:
    out = log_path(run_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    private_dir = out.parent / "runner"
    private_dir.mkdir(parents=True, exist_ok=True)
    facts: dict[str, dict] = {}
    errors: dict[str, str] = {}
    statuses: dict[str, dict] = {}  # palma_status facts reported by health playbooks

    with Session(engine) as s:
        run = s.get(Run, run_id)
        if run is None:
            return
        hosts = list(s.exec(select(Host).where(Host.id.in_(run.host_ids))))
        run.status = "running"
        run.started_at = utcnow()
        run.host_names = sorted(h.name for h in hosts)
        s.add(run)
        s.commit()
        playbook, check_mode, extra_vars = run.playbook, run.check_mode, dict(run.extra_vars or {})
        inventory = build_inventory(hosts)

    with out.open("a", encoding="utf-8") as fh:

        def on_event(ev: dict) -> bool:
            if ev.get("stdout"):
                fh.write(ev["stdout"] + "\n")
                fh.flush()
            data = ev.get("event_data") or {}
            host = data.get("host")
            res = data.get("res") or {}
            if ev.get("event") == "runner_on_ok" and isinstance(res, dict):
                af = res.get("ansible_facts") or {}
                if host and "ansible_distribution" in af:
                    facts[host] = af
                status = af.get("palma_status", af.get("hm_status"))  # hm_status: pre-rename name
                if host and isinstance(status, dict):
                    statuses[host] = status
            elif ev.get("event") == "runner_on_unreachable" and host:
                errors[host] = str(res.get("msg", "unreachable"))[:500] if isinstance(res, dict) else "unreachable"
            elif ev.get("event") == "playbook_on_stats":
                keys = ("ok", "changed", "dark", "failures", "skipped", "processed", "ignored", "rescued")
                final_stats.update({k: data.get(k) or {} for k in keys})
            return False

        status, rc = "error", None
        final_stats: dict[str, Any] = {}
        try:
            r = ansible_runner.run(
                private_data_dir=str(private_dir),
                project_dir=str(settings.playbooks_dir.resolve()),
                playbook=playbook,
                inventory=inventory,
                extravars=extra_vars or None,
                cmdline="--check --diff" if check_mode else None,
                envvars={
                    "ANSIBLE_HOST_KEY_CHECKING": "False",
                    "ANSIBLE_FORCE_COLOR": "1",
                    "ANSIBLE_PYTHON_INTERPRETER": "auto_silent",
                    "ANSIBLE_RETRY_FILES_ENABLED": "False",
                    "ANSIBLE_FORKS": "20",
                    "ANSIBLE_TIMEOUT": "20",
                    "ANSIBLE_SSH_ARGS": "-o ControlMaster=auto -o ControlPersist=60s -o ServerAliveInterval=15",
                },
                event_handler=on_event,
                cancel_callback=lambda: run_id in _cancel_requested,
                quiet=True,
                ident="job",
            )
            status, rc = r.status, r.rc
        except Exception as exc:  # noqa: BLE001
            log.exception("Run %s crashed", run_id)
            fh.write(f"\n[palma] run crashed: {exc}\n")

    with Session(engine) as s:
        run = s.get(Run, run_id)
        run.status = status if status in TERMINAL_STATES else "error"
        run.rc = rc
        run.stats = final_stats
        run.finished_at = utcnow()
        s.add(run)
        _apply_host_results(s, list(s.exec(select(Host).where(Host.id.in_(run.host_ids)))), final_stats, facts, errors, statuses)
        s.commit()

    shutil.rmtree(private_dir, ignore_errors=True)
    _cancel_requested.discard(run_id)
    with _lock:
        _active.pop(run_id, None)
