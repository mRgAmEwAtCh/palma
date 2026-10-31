"""Authentication: Authentik OIDC, or a single local admin account as fallback when OIDC is not configured."""

import asyncio
import hmac
from typing import Any

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .config import get_settings

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])

if settings.auth_mode == "local" and not settings.admin_password:
    raise RuntimeError(
        "No authentication configured: set OIDC_ISSUER + OIDC_CLIENT_ID for Authentik, "
        "or ADMIN_PASSWORD for the local login (AUTH_DISABLED=true only for development)"
    )

oauth = OAuth()
if settings.auth_mode == "oidc":
    oauth.register(
        name="oidc",
        server_metadata_url=settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        client_kwargs={"scope": settings.oidc_scopes},
    )

DEV_USER = {"sub": "dev", "name": "Developer", "email": None, "groups": []}


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
    pass_ok = hmac.compare_digest(body.password.encode(), settings.admin_password.encode())
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
