import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlmodel import Session, col, select

from .. import runner
from ..auth import current_user
from ..db import engine, get_session
from ..models import Host, Run, RunCreate
from ..playbooks import resolve_playbook

router = APIRouter(tags=["runs"])


@router.get("/runs", response_model=list[Run])
def list_runs(limit: int = 100, s: Session = Depends(get_session)):
    return s.exec(select(Run).order_by(col(Run.id).desc()).limit(min(limit, 500))).all()


@router.post("/runs", response_model=Run, status_code=201)
def create_run(body: RunCreate, user: dict = Depends(current_user), s: Session = Depends(get_session)):
    try:
        resolve_playbook(body.playbook)
    except FileNotFoundError as exc:
        raise HTTPException(400, "Unknown playbook") from exc
    if not body.host_ids:
        raise HTTPException(400, "Select at least one host")
    hosts = s.exec(select(Host).where(col(Host.id).in_(body.host_ids))).all()
    if len(hosts) != len(set(body.host_ids)):
        raise HTTPException(400, "Some selected hosts do not exist")
    run = runner.create_and_start(
        s,
        body.playbook,
        list(hosts),
        check_mode=body.check_mode,
        extra_vars=body.extra_vars,
        triggered_by=user.get("name") or user.get("sub"),
    )
    return run


@router.get("/runs/{run_id}", response_model=Run)
def get_run(run_id: int, s: Session = Depends(get_session)):
    run = s.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: int, s: Session = Depends(get_session)):
    run = s.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status in runner.TERMINAL_STATES:
        raise HTTPException(409, "Run already finished")
    runner.cancel(run_id)
    return {"ok": True}


@router.get("/runs/{run_id}/log", response_class=PlainTextResponse)
def get_log(run_id: int):
    path = runner.log_path(run_id)
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


@router.get("/runs/{run_id}/stream")
async def stream_log(run_id: int, request: Request):
    """Server-sent events: `log` events carry output chunks, a final `end` event carries the status."""

    def status() -> str | None:
        with Session(engine) as s:
            run = s.get(Run, run_id)
            return run.status if run else None

    if status() is None:
        raise HTTPException(404, "Run not found")

    async def gen():
        path = runner.log_path(run_id)
        offset = 0
        while True:
            if await request.is_disconnected():
                return
            st = status()
            if path.exists():
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(offset)
                    chunk = fh.read()
                    offset = fh.tell()
                if chunk:
                    data = "\n".join(f"data: {line}" for line in chunk.split("\n"))
                    yield f"event: log\n{data}\n\n"
            if st in runner.TERMINAL_STATES and not runner.is_active(run_id):
                yield f"event: end\ndata: {st}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
