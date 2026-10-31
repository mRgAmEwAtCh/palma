"""Deploys the controller's SSH public key to hosts.

Two methods, both using a password only once (never stored):
- "ssh":     log into the host itself with user + password (like ssh-copy-id)
- "proxmox": log into the Proxmox node as root and run the script inside the guest:
             `pct exec` for LXC containers, `qm guest exec` (QEMU guest agent) for VMs;
             works without a guest password and can install/start sshd
Afterwards the key login is verified by connecting with the controller key.
"""

import asyncio
import json
import logging
import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import asyncssh

from .config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

CONNECT_TIMEOUT = 15
PCT_TIMEOUT = 600

_INSTALL_KEY = r"""
U={user}
KEY={key}
H=$(awk -F: -v u="$U" '$1==u {{print $6}}' /etc/passwd)
[ -n "$H" ] || {{ echo "user $U does not exist" >&2; exit 3; }}
mkdir -p "$H/.ssh"
touch "$H/.ssh/authorized_keys"
KEYBODY=$(echo "$KEY" | awk '{{print $2}}')
if grep -qF "$KEYBODY" "$H/.ssh/authorized_keys"; then echo "key already present"; else echo "$KEY" >> "$H/.ssh/authorized_keys"; echo "key added"; fi
chmod 700 "$H/.ssh"
chmod 600 "$H/.ssh/authorized_keys"
chown -R "$U":"$(id -gn "$U")" "$H/.ssh"
"""

_ENSURE_SSHD = r"""
if ! command -v sshd >/dev/null 2>&1 && [ ! -x /usr/sbin/sshd ]; then
  if command -v apk >/dev/null 2>&1; then
    apk add --no-cache openssh >/dev/null || exit 4
  elif command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    { apt-get update -qq && apt-get install -y -qq openssh-server; } >/dev/null || exit 4
  else
    echo "no supported package manager to install sshd" >&2; exit 4
  fi
  echo "openssh-server installed"
fi
if command -v rc-service >/dev/null 2>&1; then
  rc-update add sshd default >/dev/null 2>&1 || true
  rc-service sshd status >/dev/null 2>&1 || { rc-service sshd start >/dev/null && echo "sshd started"; }
elif command -v systemctl >/dev/null 2>&1; then
  if ! systemctl is-active --quiet ssh && ! systemctl is-active --quiet sshd && ! systemctl is-active --quiet ssh.socket; then
    systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd >/dev/null 2>&1 || true
    echo "sshd started"
  fi
fi
"""


@dataclass
class DeployResult:
    host_id: int
    name: str
    ok: bool
    verified: bool
    message: str

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Target:
    host_id: int
    name: str
    address: str
    port: int
    user: str
    vmid: int | None = None
    guest_type: str = "lxc"  # lxc | qemu


def controller_public_key() -> str | None:
    key = Path(settings.ssh_key_path)
    pub = Path(f"{key}.pub")
    if pub.exists():
        return pub.read_text().strip() or None
    if key.exists():
        r = subprocess.run(["ssh-keygen", "-y", "-f", str(key)], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None
    return None


def install_script(user: str, key: str, ensure_sshd: bool = False) -> str:
    body = _INSTALL_KEY.format(user=shlex.quote(user), key=shlex.quote(key))
    return "set -e\n" + (_ENSURE_SSHD if ensure_sshd else "") + body


def _password_options(username: str, password: str, port: int = 22) -> dict:
    return {
        "port": port,
        "username": username,
        "password": password,
        "known_hosts": None,
        "agent_path": None,
        "client_keys": None,
        "preferred_auth": "keyboard-interactive,password",
        "connect_timeout": CONNECT_TIMEOUT,
    }


def _describe(exc: BaseException) -> str:
    if isinstance(exc, asyncssh.PermissionDenied):
        return "login failed (wrong user/password, or password login disabled)"
    if isinstance(exc, (OSError, asyncio.TimeoutError)):
        return f"cannot connect: {exc or exc.__class__.__name__}"
    return f"{exc.__class__.__name__}: {exc}"


def _last_line(text: str) -> str:
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


async def verify_key(t: Target) -> tuple[bool, str]:
    try:
        async with asyncssh.connect(
            t.address,
            port=t.port,
            username=t.user,
            client_keys=[settings.ssh_key_path],
            agent_path=None,
            known_hosts=None,
            preferred_auth="publickey",
            connect_timeout=CONNECT_TIMEOUT,
        ) as conn:
            await conn.run("true", check=True, timeout=30)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, _describe(exc)


async def _finish(t: Target, ok: bool, message: str) -> DeployResult:
    if not ok:
        return DeployResult(t.host_id, t.name, False, False, message)
    verified, err = await verify_key(t)
    msg = message + ("; key login verified" if verified else f"; key login check failed: {err}")
    return DeployResult(t.host_id, t.name, True, verified, msg)


async def deploy_via_ssh(t: Target, password: str, key: str) -> DeployResult:
    try:
        async with asyncssh.connect(t.address, **_password_options(t.user, password, t.port)) as conn:
            r = await conn.run(f"sh -c {shlex.quote(install_script(t.user, key))}", timeout=120)
    except Exception as exc:  # noqa: BLE001
        return DeployResult(t.host_id, t.name, False, False, _describe(exc))
    if r.exit_status != 0:
        return DeployResult(t.host_id, t.name, False, False, _last_line(r.stderr) or f"exit code {r.exit_status}")
    return await _finish(t, True, _last_line(r.stdout))


async def deploy_via_proxmox_node(
    node_address: str,
    username: str,
    password: str,
    targets: list[Target],
    key: str,
    ensure_sshd: bool,
    node_port: int = 22,
) -> list[DeployResult]:
    try:
        conn = await asyncssh.connect(node_address, **_password_options(username, password, node_port))
    except Exception as exc:  # noqa: BLE001
        msg = f"Proxmox node {node_address}: {_describe(exc)}"
        return [DeployResult(t.host_id, t.name, False, False, msg) for t in targets]

    results: list[DeployResult] = []
    async with conn:
        for t in targets:
            try:
                results.append(await _deploy_in_guest(conn, t, key, ensure_sshd))
            except Exception as exc:  # noqa: BLE001
                results.append(DeployResult(t.host_id, t.name, False, False, _describe(exc)))
    return results


def parse_qm_exec(stdout: str) -> tuple[int | None, str, str]:
    """Parses `qm guest exec` JSON output -> (exitcode or None if it did not finish, stdout, stderr)."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None, "", stdout.strip()
    code = data.get("exitcode") if data.get("exited") else None
    return code, data.get("out-data", ""), data.get("err-data", "")


async def _deploy_in_guest(
    conn: asyncssh.SSHClientConnection, t: Target, key: str, ensure_sshd: bool
) -> DeployResult:
    vmid = int(t.vmid)
    tool = "qm" if t.guest_type == "qemu" else "pct"
    status = await conn.run(f"{tool} status {vmid}", timeout=30)
    if status.exit_status != 0:
        return DeployResult(t.host_id, t.name, False, False, _last_line(status.stderr) or f"{tool} failed")
    if "running" not in status.stdout:
        kind = "VM" if tool == "qm" else "container"
        return DeployResult(t.host_id, t.name, False, False, f"{kind} is not running")

    script = install_script(t.user, key, ensure_sshd)
    if tool == "qm":
        r = await conn.run(
            f"qm guest exec {vmid} --timeout {PCT_TIMEOUT} -- sh -c {shlex.quote(script)}", timeout=PCT_TIMEOUT + 30
        )
        if r.exit_status != 0:
            err = _last_line(r.stderr) or f"exit code {r.exit_status}"
            return DeployResult(t.host_id, t.name, False, False, f"guest agent: {err}")
        code, out, err_out = parse_qm_exec(r.stdout)
        if code is None:
            return DeployResult(t.host_id, t.name, False, False, _last_line(err_out) or "guest command did not finish")
    else:
        r = await conn.run(f"pct exec {vmid} -- sh -c {shlex.quote(script)}", timeout=PCT_TIMEOUT)
        code, out, err_out = r.exit_status, r.stdout, r.stderr

    if code != 0:
        err = _last_line(err_out) or f"exit code {code}"
        if code == 4:
            err = f"could not install sshd: {err}"
        return DeployResult(t.host_id, t.name, False, False, err)
    message = ", ".join(line for line in (out or "").strip().splitlines() if line.strip())
    return await _finish(t, True, message)
