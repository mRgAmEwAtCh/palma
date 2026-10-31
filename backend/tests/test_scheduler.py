from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import runner, scheduler
from app.db import engine
from app.main import app
from app.models import Host, Run, Schedule


@pytest.fixture()
def client(monkeypatch):
    started: list[int] = []
    monkeypatch.setattr(runner, "start", lambda run_id: started.append(run_id))
    with TestClient(app) as c:
        c.started = started
        yield c


def _host(c, name, **kw):
    r = c.post("/api/hosts", json={"name": name, "address": "10.66.0.1", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_validate_cron():
    assert scheduler.validate_cron(" 0  */6 * * * ") == "0 */6 * * *"
    for bad in ["* * * *", "99 * * * *", "every day"]:
        with pytest.raises(ValueError):
            scheduler.validate_cron(bad)


def test_next_runs_respect_timezone_and_dst():
    # Europe/Berlin (configured in conftest): 03:00 local is 01:00Z in summer time, 02:00Z after 2026-10-25
    before = scheduler.next_runs("0 3 * * *", datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc), count=3)
    assert [d.isoformat() for d in before] == [
        "2026-10-24T01:00:00+00:00",
        "2026-10-25T02:00:00+00:00",
        "2026-10-26T02:00:00+00:00",
    ]


def test_resolve_targets(client):
    a = _host(client, "sched-a", tags=["sched-x"])
    b = _host(client, "sched-b", tags=["sched-y"], kind="baremetal")
    _host(client, "sched-c", tags=["sched-x"], enabled=False)
    with Session(engine) as s:
        names = lambda sch: [h.name for h in scheduler.resolve_targets(s, sch)]  # noqa: E731
        assert names(Schedule(name="t", playbook="ping.yml", cron="* * * * *", target_tags=["sched-x"])) == ["sched-a"]
        assert names(Schedule(name="t", playbook="ping.yml", cron="* * * * *", target_host_ids=[b["id"], a["id"]])) == [
            "sched-a",
            "sched-b",
        ]
        all_names = names(Schedule(name="t", playbook="ping.yml", cron="* * * * *"))
        assert "sched-a" in all_names and "sched-c" not in all_names


def test_tick_triggers_due_schedule_and_skips_overlap(client):
    h = _host(client, "sched-tick", tags=["sched-tick"])
    sch = client.post(
        "/api/schedules",
        json={"name": "Tick test", "playbook": "health.yml", "cron": "*/5 * * * *", "target_tags": ["sched-tick"],
              "extra_vars": {"disk_warn_percent": 70}},
    ).json()
    assert sch["target_count"] == 1 and sch["next_run_at"]

    later = datetime.now(timezone.utc) + timedelta(minutes=6)
    assert scheduler.tick(later) >= 1
    with Session(engine) as s:
        stored = s.get(Schedule, sch["id"])
        run = s.get(Run, stored.last_run_id)
        assert run.schedule_id == sch["id"] and run.host_ids == [h["id"]]
        assert run.triggered_by == "schedule: Tick test" and run.extra_vars == {"disk_warn_percent": 70}
        assert scheduler.as_utc(stored.next_run_at) > later
    assert run.id in client.started

    # previous run is still "pending" (runner.start is mocked) -> next trigger is skipped
    r = client.post(f"/api/schedules/{sch['id']}/run")
    assert r.status_code == 409 and "still active" in r.json()["detail"]


def test_schedule_api_validation_and_preview(client):
    assert client.post("/api/schedules", json={"name": "x", "playbook": "ping.yml", "cron": "bad"}).status_code == 400
    assert client.post("/api/schedules", json={"name": "x", "playbook": "nope.yml", "cron": "0 * * * *"}).status_code == 400
    p = client.get("/api/schedules/preview", params={"cron": "0 3 * * 1"}).json()
    assert p["valid"] and len(p["next"]) == 3
    assert client.get("/api/schedules/preview", params={"cron": "0 25 * * *"}).json()["valid"] is False

    sch = client.post("/api/schedules", json={"name": "Off", "playbook": "ping.yml", "cron": "0 * * * *", "enabled": False}).json()
    assert sch["next_run_at"] is None
    sch = client.patch(f"/api/schedules/{sch['id']}", json={"enabled": True}).json()
    assert sch["next_run_at"] is not None
    assert client.delete(f"/api/schedules/{sch['id']}").status_code == 204


def test_palma_status_is_stored_on_host(client):
    h = _host(client, "sched-health")
    status = {"level": "warning", "checks": {"updates": {"level": "warning", "summary": "3", "details": []}}}
    with Session(engine) as s:
        host = s.get(Host, h["id"])
        runner._apply_host_results(s, [host], {"processed": {host.name: 1}}, {}, {}, {host.name: status})
        s.commit()
    got = client.get(f"/api/hosts/{h['id']}").json()
    assert got["health"] == status and got["health_checked_at"] and got["last_seen"]
