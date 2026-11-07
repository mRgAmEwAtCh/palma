from functools import lru_cache
import json
from pathlib import Path
import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    playbooks_dir: Path = Path("../playbooks")
    frontend_dist: Path = Path("../frontend/dist")

    timezone: str = "UTC"
    scheduler_enabled: bool = True

    ssh_key_path: str = str(Path.home() / ".ssh" / "id_ed25519")
    default_ssh_user: str = "root"

    public_url: str = "http://localhost:8080"
    session_secret: str = "change-me"
    session_https_only: bool = False

    auth_disabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_allowed_groups: str = ""

    # Local fallback login, used when OIDC is not configured
    admin_username: str = "admin"
    admin_password: str = ""
    admin_password_hash: str = ""

    @property
    def needs_account(self) -> bool:
        return self.auth_mode == "local" and not (self.admin_password or self.admin_password_hash)

    @property
    def auth_mode(self) -> str:
        if self.auth_disabled:
            return "disabled"
        if self.oidc_issuer and self.oidc_client_id:
            return "oidc"
        return "local"

    @property
    def allowed_groups(self) -> set[str]:
        return {g.strip() for g in self.oidc_allowed_groups.split(",") if g.strip()}

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if not settings.session_secret or settings.session_secret == "change-me":
        path = settings.data_dir / "session-secret"
        if not path.exists():
            with path.open("x", encoding="utf-8") as f:
                path.chmod(0o600)
                f.write(secrets.token_hex(32))
        settings.session_secret = path.read_text(encoding="utf-8").strip()
        if not settings.session_secret:
            raise RuntimeError("The persisted session secret is empty")
    account = settings.data_dir / "admin.json"
    if account.exists() and not settings.admin_password:
        stored = json.loads(account.read_text(encoding="utf-8"))
        settings.admin_username = stored["username"]
        settings.admin_password_hash = stored["password_hash"]
    return settings
