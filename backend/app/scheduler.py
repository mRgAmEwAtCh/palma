"""Cron-based execution of playbooks. Runs inside the app process (single worker)."""

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from cronsim import CronSim, CronSimError
from sqlmodel import Session, col, select

from . import runner
from .config import get_settings
from .db import engine
from .models import Host, Run, Schedule, utcnow
from .playbooks import resolve_playbook

log = logging.getLogger(__name__)
settings = get_settings()
TICK_SECONDS = 20


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tz info; stored timestamps are UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def validate_cron(expr: str) -> str:
    expr = " ".join(expr.split())
    if len(expr.split()) != 5:
        raise ValueError("Use 5 fields: minute hour day-of-month month day-of-week")
    try:
        CronSim(expr, datetime.now(ZoneInfo(settings.timezone)))
    except CronSimError as exc:
        raise ValueError(f"Invalid cron expression: {exc}") from exc
    return expr


def next_runs(expr: str, after: datetime | None = None, count: int = 1) -> list[datetime]:
    """Next fire times (UTC), evaluated in the configured timezone (DST-aware)."""
    tz = ZoneInfo(settings.timezone)
    start = (as_utc(after) or datetime.now(timezone.utc)).astimezone(tz)
    it = CronSim(expr, start)
    return [next(it).astimezone(timezone.utc) for _ in range(count)]


def resolve_targets(s: Session, sch: Schedule) -> list[Host]:
    hosts = [h for h in s.exec(select(Host).order_by(Host.name)) if h.enabled]
    if sch.target_host_ids:
        wanted = set(sch.target_host_ids)
        return [h for h in hosts if h.id in wanted]
    if sch.target_tags:
        tags = set(sch.target_tags)
        return [h for h in hosts if h.kind in tags or tags.intersection(h.tags or [])]
    return hosts


def trigger(s: Session, sch: Schedule, manual: bool = False) -> Run | None:
    """Starts a run for the schedule unless its previous run is still active. Records the outcome on the schedule."""
    sch.last_run_at = utcnow()
    run = None
    if sch.last_run_id and (prev := s.get(Run, sch.last_run_id)) and prev.status in ("pending", "running"):
        sch.last_message = f"skipped: previous run #{prev.id} still active"
    else:
        try:
            resolve_playbook(sch.playbook)
        except FileNotFoundError:
            sch.last_message = f"playbook {sch.playbook} not found"
        else:
            hosts = resolve_targets(s, sch)
            if not hosts:
                sch.last_message = "no enabled hosts match the target"
            else:
                label = f"{'manual' if manual else 'schedule'}: {sch.name}"
                run = runner.create_and_start(
                    s, sch.playbook, hosts, extra_vars=sch.extra_vars, triggered_by=label, schedule_id=sch.id
                )
                sch.last_run_id = run.id
                sch.last_message = None
    if sch.last_message:
        log.warning("Schedule %s: %s", sch.name, sch.last_message)
    s.add(sch)
    s.commit()
    return run


def tick(now: datetime | None = None) -> int:
    """Runs all due schedules; returns how many were triggered."""
    now = as_utc(now) or datetime.now(timezone.utc)
    started = 0
    with Session(engine) as s:
        for sch in s.exec(select(Schedule).where(col(Schedule.enabled) == True)):  # noqa: E712
            due = as_utc(sch.next_run_at)
            if due is None:
                sch.next_run_at = next_runs(sch.cron, now)[0]
                s.add(sch)
                s.commit()
                continue
            if due <= now:
                sch.next_run_at = next_runs(sch.cron, now)[0]
                if trigger(s, sch):
                    started += 1
    return started


def reset_next_runs() -> None:
    """On startup: plan from now on; runs missed while the app was down are not caught up."""
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        for sch in s.exec(select(Schedule)):
            try:
                sch.next_run_at = next_runs(sch.cron, now)[0] if sch.enabled else None
            except (CronSimError, ValueError):
                sch.next_run_at = None
                sch.last_message = "invalid cron expression"
            s.add(sch)
        s.commit()


async def loop() -> None:
    reset_next_runs()
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:  # noqa: BLE001
            log.exception("Scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)
