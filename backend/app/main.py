import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import auth, runner, scheduler
from .config import get_settings
from .db import init_db
from .routers import hosts, keys, playbooks, proxmox, runs, schedules, system

logging.basicConfig(level=logging.INFO)
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    runner.recover_interrupted_runs()
    task = asyncio.create_task(scheduler.loop()) if settings.scheduler_enabled else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Palma", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="palma_session",
    same_site="lax",
    https_only=settings.session_https_only,
    max_age=7 * 24 * 3600,
)

app.include_router(auth.router)
protected = [Depends(auth.current_user)]
app.include_router(system.router, prefix="/api")
for r in (hosts.router, keys.router, playbooks.router, proxmox.router, runs.router, schedules.router):
    app.include_router(r, prefix="/api", dependencies=protected)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


dist = settings.frontend_dist.resolve()
if (dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
