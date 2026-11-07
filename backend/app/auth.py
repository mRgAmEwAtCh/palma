"""Authentication: Authentik OIDC, or a single local admin account as fallback when OIDC is not configured."""

import asyncio
import hmac
import hashlib
import secrets
import json
import logging
from threading import Lock
from typing import Any

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
import httpx2

from .config import OIDCSettings, apply_oidc, get_settings

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()
setup_lock = Lock()
log = logging.getLogger(__name__)


def register_oidc(config: OIDCSettings | None = None):
    registry = OAuth() if config else oauth
    return registry.register(
        name="setup_oidc" if config else "oidc",
        overwrite=True,
        server_metadata_url=(
            str(config.issuer).rstrip("/") if config else settings.oidc_issuer.rstrip("/")
        ) + "/.well-known/openid-configuration",
        client_id=config.client_id if config else settings.oidc_client_id,
        client_secret=config.client_secret if config else settings.oidc_client_secret,
        client_kwargs={"scope": settings.oidc_scopes},
    )


if settings.auth_mode == "oidc":
    register_oidc()


def pending_oidc(request: Request) -> OIDCSettings:
    path = settings.data_dir / "oidc-pending.json"
    if not settings.needs_account or not path.exists():
        raise HTTPException(409, "OIDC setup is not pending")
    stored = json.loads(path.read_text(encoding="utf-8"))
    if not hmac.compare_digest(request.session.get("oidc_setup_claim", ""), stored["claim"]):
        raise HTTPException(403, "Continue OIDC setup in the browser that configured it")
    return OIDCSettings.model_validate(stored["config"])


@router.get("/setup-login")
async def setup_login(request: Request):
    config = pending_oidc(request)
    client = register_oidc(config)
    try:
        return await client.authorize_redirect(request, str(config.public_url).rstrip("/") + "/auth/setup-callback")
    except httpx2.HTTPError as exc:
        log.exception("OIDC setup provider discovery failed")
        raise HTTPException(502, "Cannot reach OIDC provider; return to setup and check issuer, TLS and connectivity") from exc


@router.get("/setup-callback")
async def setup_callback(request: Request):
    config = pending_oidc(request)
    client = register_oidc(config)
    try:
        token = await client.authorize_access_token(request)
        info = token.get("userinfo") or await client.userinfo(token=token)
    except OAuthError as exc:
        raise HTTPException(401, f"OIDC error: {exc.error}; return to setup to retry or choose local login") from exc
    except httpx2.HTTPError as exc:
        log.exception("OIDC setup token exchange failed")
        raise HTTPException(502, "OIDC sign-in failed; return to setup and check provider connectivity and client credentials") from exc
    allowed = {g.strip() for g in config.allowed_groups.split(",") if g.strip()}
    groups = info.get("groups") or []
    if not info.get("sub"):
        raise HTTPException(401, "OIDC provider did not return a user subject")
    if allowed and not allowed.intersection(groups):
        raise HTTPException(403, "You are not a member of an allowed group; return to setup to adjust it")
    with setup_lock:
        if pending_oidc(request) != config:
            raise HTTPException(409, "OIDC configuration changed during sign-in; retry with the current configuration")
        path = settings.data_dir / "oidc.json"
        temporary = settings.data_dir / "oidc-verified.tmp"
        try:
            if path.exists():
                raise HTTPException(409, "OIDC is already configured")
            with temporary.open("w", encoding="utf-8") as f:
                temporary.chmod(0o600)
                f.write(config.model_dump_json())
            temporary.replace(path)
        except OSError as exc:
            log.exception("Persisting verified OIDC configuration failed")
            raise HTTPException(500, "Cannot save OIDC settings; check server logs and data-directory permissions") from exc
        finally:
            temporary.unlink(missing_ok=True)
        apply_oidc(settings, config)
        register_oidc()
        (settings.data_dir / "oidc-pending.json").unlink()
    request.session.clear()
    request.session["user"] = {
        "sub": info["sub"], "name": info.get("name") or info.get("preferred_username") or info["sub"],
        "email": info.get("email"), "groups": groups,
    }
    return RedirectResponse("/")


DEV_USER = {"sub": "dev", "name": "Developer", "email": None, "groups": []}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"{salt}:{digest}"


def password_matches(password: str) -> bool:
    if settings.admin_password:
        return hmac.compare_digest(password.encode(), settings.admin_password.encode())
    if not settings.admin_password_hash:
        return False
    salt, expected = settings.admin_password_hash.split(":")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)


def current_user(request: Request) -> dict[str, Any]:
    if settings.auth_mode == "disabled":
        return DEV_USER
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/config")
def auth_config():
    return {"mode": settings.auth_mode}


@router.get("/login")
async def login(request: Request):
    if settings.needs_account:
        return RedirectResponse("/")
    if settings.auth_mode == "oidc":
        redirect_uri = settings.public_url.rstrip("/") + "/auth/callback"
        return await oauth.oidc.authorize_redirect(request, redirect_uri)
    if settings.auth_mode == "local":
        return RedirectResponse("/login")
    return RedirectResponse("/")


class LocalLogin(BaseModel):
    username: str
    password: str


@router.post("/local")
async def local_login(body: LocalLogin, request: Request):
    if settings.auth_mode != "local":
        raise HTTPException(status_code=404, detail="Local login is not enabled")
    user_ok = hmac.compare_digest(body.username.encode(), settings.admin_username.encode())
    pass_ok = password_matches(body.password)
    if not (user_ok and pass_ok):
        await asyncio.sleep(1)  # slow down brute force attempts
        raise HTTPException(status_code=401, detail="Invalid username or password")
    request.session.clear()
    request.session["user"] = {"sub": f"local:{settings.admin_username}", "name": settings.admin_username, "email": None, "groups": []}
    return {"ok": True}


@router.get("/callback")
async def callback(request: Request):
    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=404, detail="OIDC is not enabled")
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(status_code=401, detail=f"OIDC error: {exc.error}") from exc
    info = token.get("userinfo") or await oauth.oidc.userinfo(token=token)
    groups = info.get("groups") or []
    allowed = settings.allowed_groups
    if allowed and not allowed.intersection(groups):
        raise HTTPException(status_code=403, detail="You are not a member of an allowed group")
    request.session.clear()
    request.session["user"] = {
        "sub": info.get("sub"),
        "name": info.get("name") or info.get("preferred_username") or info.get("email"),
        "email": info.get("email"),
        "groups": groups,
    }
    return RedirectResponse("/")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    if settings.auth_mode == "oidc":
        metadata = await oauth.oidc.load_server_metadata()
        return RedirectResponse(metadata.get("end_session_endpoint") or "/")
    if settings.auth_mode == "local":
        return RedirectResponse("/login")
    return RedirectResponse("/")
