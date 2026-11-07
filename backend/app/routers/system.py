import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ..auth import current_user
from ..config import get_settings
from ..db import get_session
from ..keydeploy import controller_public_key
from ..models import SetupState
from ..repositories import list_repositories
from ..versions import check_application_version, check_versions

router = APIRouter(tags=["system"])
settings = get_settings()


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {**user, "auth_mode": settings.auth_mode}


@router.get("/system/versions", dependencies=[Depends(current_user)])
async def tool_versions(refresh: bool = False):
    return await check_versions(refresh=refresh)


@router.get("/system/application-version", dependencies=[Depends(current_user)])
async def application_version_info():
    return await check_application_version()


@router.get("/system", dependencies=[Depends(current_user)])
def system_info(s: Session = Depends(get_session)):
    key = Path(settings.ssh_key_path)
    pubkey = controller_public_key()
    try:
        ansible_version = subprocess.run(
            ["ansible", "--version"], capture_output=True, text=True, timeout=15
        ).stdout.splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        ansible_version = None
    setup = s.get(SetupState, 1)
    return {
        "ssh_key_path": str(key),
        "ssh_key_present": key.exists(),
        "ssh_public_key": pubkey,
        "default_ssh_user": settings.default_ssh_user,
        "ansible_version": ansible_version,
        "playbooks_dir": str(settings.playbooks_dir.resolve()),
        "playbook_repository": {
            "url": setup.repository_url, "ref": setup.repository_ref, "path": setup.repository_path,
        } if setup and setup.repository_url else None,
        "playbook_repositories": list_repositories(s),
    }
