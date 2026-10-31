from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import scheduler
from ..db import get_session
from ..models import Run, Schedule, ScheduleCreate, ScheduleUpdate
from ..playbooks import resolve_playbook

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _check(playbook: str | None, cron: str | None) -> str | None:
    if playbook is not None:
        try:
            resolve_playbook(playbook)
        except FileNotFoundError as exc:
            raise HTTPException(400, "Unknown playbook") from exc
    if cron is None:
        return None
    try:
        return scheduler.validate_cron(cron)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _read(s: Session, sch: Schedule) -> dict[str, Any]:
    last = s.get(Run, sch.last_run_id) if sch.last_run_id else None
    data = sch.model_dump()
    for key in ("last_run_at", "next_run_at", "created_at"):
        data[key] = scheduler.as_utc(data[key])
    data["last_run_status"] = last.status if last else None
    data["target_count"] = len(scheduler.resolve_targets(s, sch))
    return data


def _get(s: Session, schedule_id: int) -> Schedule:
    sch = s.get(Schedule, schedule_id)
    if not sch:
        raise HTTPException(404, "Schedule not found")
    return sch


@router.get("")
def list_schedules(s: Session = Depends(get_session)):
    return [_read(s, sch) for sch in s.exec(select(Schedule).order_by(Schedule.name))]


@router.get("/preview")
def preview(cron: str, count: int = 3):
    """Validates a cron expression and returns the next fire times (for live feedback in the form)."""
    try:
        expr = scheduler.validate_cron(cron)
    except ValueError as exc:
        return {"valid": False, "error": str(exc), "next": []}
    return {"valid": True, "error": None, "next": scheduler.next_runs(expr, count=min(count, 10))}


@router.post("", status_code=201)
def create_schedule(body: ScheduleCreate, s: Session = Depends(get_session)):
    cron = _check(body.playbook, body.cron)
    sch = Schedule.model_validate(body)
    sch.cron = cron
    sch.next_run_at = scheduler.next_runs(cron)[0] if sch.enabled else None
    s.add(sch)
    s.commit()
    s.refresh(sch)
    return _read(s, sch)


@router.patch("/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleUpdate, s: Session = Depends(get_session)):
    sch = _get(s, schedule_id)
    data = body.model_dump(exclude_unset=True)
    cron = _check(data.get("playbook"), data.get("cron"))
    if cron:
        data["cron"] = cron
    sch.sqlmodel_update(data)
    sch.next_run_at = scheduler.next_runs(sch.cron)[0] if sch.enabled else None
    s.add(sch)
    s.commit()
    s.refresh(sch)
    return _read(s, sch)


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, s: Session = Depends(get_session)):
    s.delete(_get(s, schedule_id))
    s.commit()


@router.post("/{schedule_id}/run")
def run_now(schedule_id: int, s: Session = Depends(get_session)):
    sch = _get(s, schedule_id)
    run = scheduler.trigger(s, sch, manual=True)
    if not run:
        raise HTTPException(409, sch.last_message or "Could not start run")
    return {"run_id": run.id}


@router.get("/{schedule_id}/runs")
def schedule_runs(schedule_id: int, limit: int = 20, s: Session = Depends(get_session)) -> list[dict]:
    _get(s, schedule_id)
    runs = s.exec(select(Run).where(Run.schedule_id == schedule_id).order_by(Run.id.desc()).limit(min(limit, 100)))
    return [{"id": r.id, "status": r.status, "created_at": r.created_at} for r in runs]

