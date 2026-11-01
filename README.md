<p align="center">
  <img src="docs/logo.svg" alt="Palma logo" width="128" height="128">
</p>

<h1 align="center">Palma</h1>

<p align="center">
  <b>P</b>roxmox <b>A</b>nd <b>L</b>inux <b>M</b>aintenance via <b>A</b>nsible<br>
  <i>Your homelab, maintained from the palm of your hand.</i>
</p>

<p align="center">
  <a href="https://github.com/mRgAmEwAtCh/palma/actions/workflows/docker.yml"><img src="https://github.com/mRgAmEwAtCh/palma/actions/workflows/docker.yml/badge.svg" alt="CI &amp; Docker"></a>
  <a href="https://github.com/mRgAmEwAtCh/palma/pkgs/container/palma"><img src="https://img.shields.io/badge/ghcr.io-mrgamewatch%2Fpalma-f4a63c?logo=docker&amp;logoColor=white" alt="Container image"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-3fb950" alt="MIT license"></a>
</p>

Palma is a small, mobile-first web app on top of Ansible for maintaining homelab hosts: Proxmox LXC containers and VMs,
and bare-metal boxes like OpenMediaVault or a Raspberry Pi with Armbian. Supports Debian, Ubuntu, Armbian, OMV and
Alpine targets.

- **Hosts**: manage hosts manually or import LXC containers and VMs from one or more Proxmox VE nodes via API token.
- **Run playbooks on a checked list of hosts**: tick hosts individually or tap a tag/type chip to select a group.
  Optional dry run (`--check --diff`) and extra vars.
- **Live output** streamed to the browser, per-host result (ok / changed / failed / unreachable), cancel,
  "run again" and "retry failed hosts".
- **History** of all runs. OS facts and reachability are updated on each run.
- **Schedules**: run any playbook by cron (e.g. the health check every 6 h) on all hosts, hosts with certain
  tags/types, or selected hosts (History tab → Schedules).
- **Health labels** on every host (Hosts tab): Docker containers, disk usage, pending updates/reboot and failed systemd
  units, colored ok / warning / critical, with details in the host sheet.
- **Login via Authentik (OIDC)**, optionally restricted to Authentik groups, with a **local admin login as fallback**
  when no OIDC is configured.
- Installable on Android (Chrome → *Add to home screen*).
- **Tool maintenance check** (Settings tab): compares the installed `ansible-core`, `ansible-runner` and the
  `community.general` collection against the latest releases on PyPI / Ansible Galaxy (cached for 6 h). A dot on the
  Settings tab signals available updates. Python and npm dependencies are pinned and kept current by
  [Dependabot](.github/dependabot.yml); after merging an update, pull the new image (`docker compose pull && docker compose
  up -d`) or, when building locally, `git pull && docker compose up -d --build`.

## Architecture

| Part      | Tech                                                                    |
|-----------|-------------------------------------------------------------------------|
| Backend   | FastAPI, SQLModel/SQLite, [ansible-runner](https://ansible.readthedocs.io/projects/runner/), Authlib |
| Frontend  | React + TypeScript (Vite), no UI framework, mobile-first CSS             |
| Playbooks | `playbooks/*.yml`, mounted into the container and listed automatically     |
| Deploy    | Single Docker container via Docker Compose                              |

For every run, an inventory is generated from just the selected hosts. Each tag and host type (`lxc`, `baremetal`, …)
becomes an inventory group, so playbooks should target `hosts: all`.

## Starter playbooks

| Playbook              | Purpose                                                                                       |
|-----------------------|-----------------------------------------------------------------------------------------------|
| `ping.yml`            | Connectivity check, gathers facts (updates OS info in the UI)                                  |
| `bootstrap.yml`       | Installs `python3` via raw commands (fresh Alpine/Debian LXCs)                                 |
| `update.yml`          | `apt dist-upgrade` / `apk upgrade` / `omv-upgrade`, reports whether a reboot is required        |
| `reboot.yml`          | Reboots hosts with `/var/run/reboot-required` (or all with `force_reboot=true`), one at a time |
| `safe_reboot.yml`     | Graceful reboot request for LXC guests, Proxmox hosts and bare-metal Linux boxes, with Proxmox host protection |
| `health.yml`          | Docker container state, disk usage, pending updates, reboot flag, failed systemd units; sets the host health labels |
| `docker_cleanup.yml`  | `docker system prune -a` on hosts with Docker (`prune_volumes=true` to include volumes)         |
| `docker_compose_update.yml` | Detects Compose stacks via container labels, runs `pull` + `up -d` per stack, then removes the replaced images (`compose_include`/`compose_exclude`, `compose_prune_images=dangling\|all\|none`). Dry run lists the detected stacks |
| `sssd_ldap.yml`       | Authentik LDAP login via SSSD (Debian/Ubuntu); needs `playbooks/vars/sssd_vars.yml`             |

For `safe_reboot.yml`, set `reboot_requested: true` to reboot even without the reboot-required flag.
Proxmox nodes also require `allow_proxmox_host_reboot: true` to explicitly acknowledge guest downtime.
The playbook uses normal OS shutdown (including Proxmox guest shutdown), waits for recovery, and stops
the run on failure before rebooting another device. It does not migrate guests, force a reboot, or
verify cluster quorum. Check guest shutdown settings and quorum before approval. Never select Palma's
own host or its Proxmox node. Dry run checks the safeguards and previews reboots without requesting them.
LXC guests are managed over SSH and need Python and a working init system.

Add your own playbooks in the UI (**Settings → Manage playbooks**, or **Edit** / **Manage playbooks…** in the playbook
picker), or drop a `.yml` file into `playbooks/`. The first play's `name` is used as the title, the leading `#` comment
block as the description, and the play-level `vars:` as the defaults that are prefilled when running.

The editor validates before saving, in three stages, and reports issues with line numbers (tap one to jump to the line):

1. **YAML** syntax (Ansible tags such as `!vault` are accepted)
2. **Structure**: a list of plays, each with `hosts` (or `import_playbook`). Warnings for plays that don't target `all`
   (the app only puts the selected hosts into the inventory) or have no tasks
3. **`ansible-playbook --syntax-check`**, run inside `playbooks/` so relative `tasks/`, `vars/` and `templates/` resolve.
   This catches unknown modules, invalid keywords and missing includes

Files with errors are not saved. Every save or delete keeps the previous version in `data/playbook-history/<file>/` (last 20).
Only top-level playbook files can be edited in the UI; `tasks/`, `templates/` and `vars/` are managed on disk.

## Deployment (Docker Compose)

```bash
cp .env.example .env            # then edit it, see below
mkdir -p ssh && cp /path/to/controller_key ssh/id_ed25519   # or point SSH_KEY_DIR to an existing key dir
docker compose up -d --build
```

The app listens on `PORT` (default 8080). The controller's public key is shown under **Settings**. Add it to
`~/.ssh/authorized_keys` of the SSH user on every managed host.

### Prebuilt image

Multi-arch images (`linux/amd64`, `linux/arm64`) are published to the GitHub Container Registry by
[GitHub Actions](.github/workflows/docker.yml):

| Tag | Built from |
|-----|------------|
| `latest`, `1.2.3`, `1.2`, `1` | release tags `v1.2.3` |
| `edge` | every push to `main` |
| `sha-<commit>` | every push |

To use it instead of building locally, replace `build: .` and `image: palma:latest` in `docker-compose.yml` with:

```yaml
    image: ghcr.io/mrgamewatch/palma:latest
```

and run `docker compose pull && docker compose up -d`. The repository checkout is still needed for `playbooks/`, which
is mounted into the container.

### Releasing

Tag a commit to publish a versioned image (the tests must pass first):

```bash
git tag v1.0.0 && git push origin v1.0.0
```

### Authentication

The login mode is chosen automatically:

| Configured                          | Mode                                                         |
|-------------------------------------|--------------------------------------------------------------|
| `OIDC_ISSUER` + `OIDC_CLIENT_ID`    | Authentik OIDC login                                         |
| otherwise, `ADMIN_PASSWORD` set     | Local login page with `ADMIN_USERNAME` / `ADMIN_PASSWORD`    |
| neither                             | App refuses to start (unless `AUTH_DISABLED=true` for dev)   |

### Authentik

1. In Authentik, go to **Applications → Applications → Create with provider** and choose **OAuth2/OpenID Provider**.
   - Client type: *Confidential*
   - Redirect URI: `<PUBLIC_URL>/auth/callback` (e.g. `http://192.168.1.10:8080/auth/callback`)
   - Scopes: `openid`, `email`, `profile` (default mappings)
2. Copy the client ID and secret into `.env`. Set `OIDC_ISSUER` to the provider's *OpenID Configuration Issuer*
   (e.g. `https://auth.example.com/application/o/palma/`).
3. Optional: set `OIDC_ALLOWED_GROUPS` (comma separated) to restrict access, and/or bind the application to a group in Authentik.
4. Set `SESSION_SECRET` (`openssl rand -hex 32`). Behind an HTTPS reverse proxy, also set `SESSION_HTTPS_ONLY=true`
   and use the HTTPS URL as `PUBLIC_URL`.

### Schedules and health labels

Schedules run a playbook by **cron expression** (5 fields, evaluated in `TIMEZONE`, DST-aware). The target is resolved
at run time: selected hosts, hosts with any of the chosen tags/types, or all enabled hosts. Runs never overlap (a due
run is skipped while the previous one is still active), and runs missed while the app was down are not caught up.
Scheduled runs show up in the history as `schedule: <name>`.

Any playbook can update the health labels by setting the fact `palma_status` per host:

```yaml
palma_status:
  level: warning            # ok | warning | critical (worst check)
  checks:
    disk: { level: ok, summary: "58%", details: ["/: 57.9% of 15.6 GB"] }
    updates: { level: warning, summary: "106", details: [] }
```

`health.yml` reports these checks:

| Check   | Level |
|---------|-------|
| docker  | **critical**: container unhealthy, restarting, out of memory, or crashed (exit code ≠ 0/130/137/143) despite a restart policy; **warning**: `restart: always` container stopped or a container paused. Containers stopped on purpose and one-off jobs are ignored; exclude containers with `docker_ignore_containers` |
| disk    | fullest filesystem: **warning** ≥ `disk_warn_percent` (85), **critical** ≥ `disk_crit_percent` (95) |
| updates | **warning** if updates are pending or a reboot is required |
| units   | **warning** if systemd units have failed |

### Installing the controller SSH key

Use **Install SSH key…** on the Hosts tab, in a host's edit sheet, or per source on the Proxmox tab. You enter a
password once; it is not stored. Afterwards the app verifies that key login works.

| Method            | How it works                                                                                                  | Use for                       |
|-------------------|---------------------------------------------------------------------------------------------------------------|-------------------------------|
| Via Proxmox node  | SSH to the node (IP from `/cluster/status`) as root, then `pct exec <vmid>` (containers) or `qm guest exec <vmid>` (VMs, needs a running QEMU guest agent) adds the key inside the guest. Optionally installs and starts `openssh-server`. No guest password needed | imported LXC containers and VMs |
| Direct SSH        | Password login to the host itself (like `ssh-copy-id`). The key is installed for the login user, which becomes the host's SSH user | bare metal, VMs, anything else |

> Host keys of the nodes/hosts are not verified during this one-time login (same as accepting the fingerprint on
> first `ssh`). Non-root SSH users need passwordless `sudo` for playbooks that use `become`.

### Proxmox import

Create an API token per Proxmox node/cluster (**Datacenter → Permissions → API Tokens**) and grant it the
**PVEAuditor** role on `/`. Add it on the **Proxmox** tab, then tap **Discover guests** and import the containers and VMs
you want.

- **LXC**: the IP comes from the container's interfaces when it's running; otherwise from a static `ip=` in `net0`.
- **VMs**: the IP comes from the **QEMU guest agent** (`qemu-guest-agent` installed in the VM and *QEMU Guest Agent*
  enabled in the VM options; the token needs `VM.GuestAgent.Audit` on PVE 9, which PVEAuditor includes, or
  `VM.Monitor` on PVE 8). Otherwise it comes from a cloud-init `ipconfig0`. Docker/bridge interfaces are ignored.
  Windows VMs are listed but not imported, and templates are hidden.
- Guests without an IP show the reason. Re-importing refreshes the IP, node, status and type. Imported hosts are
  tagged `proxmox`, `<source name>` and any Proxmox tags, and get the type `lxc` or `vm`.

> The Proxmox token secret is stored in the SQLite database in `data/`. Protect that directory accordingly.

## Development


```bash
# backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
ansible-galaxy collection install -r ../playbooks/requirements.yml
AUTH_DISABLED=true SSH_KEY_PATH=~/.ssh/id_ed25519 .venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/python -m pytest

# frontend (proxies /api and /auth to :8000)
cd frontend
npm install
npm run dev
```

## Configuration reference

All settings are environment variables (see `.env.example`): `PUBLIC_URL`, `SESSION_SECRET`, `SESSION_HTTPS_ONLY`,
`OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_SCOPES`, `OIDC_ALLOWED_GROUPS`, `ADMIN_USERNAME`,
`ADMIN_PASSWORD`, `AUTH_DISABLED`, `TIMEZONE`,
`DEFAULT_SSH_USER`, `SSH_KEY_PATH`, `SSH_KEY_DIR`, `DATA_DIR`, `PLAYBOOKS_DIR`, `BIND_ADDRESS`, `PORT`.

## Dependency updates

[Dependabot](.github/dependabot.yml) checks every Monday and opens pull requests for:

| Ecosystem | Files | Grouping |
|-----------|-------|----------|
| pip | `backend/requirements.txt`, `backend/requirements-dev.txt` (exact pins) | minor + patch in one PR, majors separately |
| npm | `frontend/package.json`, `package-lock.json` | minor + patch in one PR, majors separately |
| Docker | base images in the `Dockerfile` | one PR per image |
| GitHub Actions | `.github/workflows/*.yml` | one PR for all actions |

Each PR runs the CI workflow (tests, frontend build, image build). The Ansible collection in
`playbooks/requirements.yml` is not covered by Dependabot; the tool maintenance check in the app reports its updates.

## License

[MIT](LICENSE) © 2026 Thomas Kuhnke

Palma is an independent project and is not affiliated with or endorsed by Red Hat (Ansible) or Proxmox Server Solutions.
