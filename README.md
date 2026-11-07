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
- **System-wide theme** (Settings, collapsed by default): expand System theme to choose primary/secondary colors with color pickers and a Graphite,
  Midnight, Slate or Forest background. Save persists the theme in SQLite for everyone, including login;
  **Reset to default** restores Palma's original theme. Open clients refresh within 30 seconds or on focus.
  Unsaved changes stay in the preview. Status colors remain unchanged; accent text and button fills are
  adjusted when needed for readable contrast. Theme changes require login (unless authentication is disabled).
  The public theme endpoint exposes only colors/presets so login can use the shared appearance.
- Installable on Android (Chrome → *Add to home screen*).
- **Standalone first-run setup**: start with only the Compose file, create an administrator account,
  generate or reuse a persistent SSH key, select a playbook repository, and optionally configure Proxmox
  using the built-in requirements guide.
- **Tool maintenance check** (Settings tab, collapsed by default with status visible): expand to compare the installed `ansible-core`, `ansible-runner` and the
  `community.general` collection against the latest releases on PyPI / Ansible Galaxy (cached for 6 h). A dot on the
  Settings tab signals available updates. Python and npm dependencies are pinned and kept current by
  [Dependabot](.github/dependabot.yml); after merging an update, pull the new image (`docker compose pull && docker compose
  up -d`) or, when building locally, rebuild the image as described under **Prebuilt image**.

## Architecture

| Part      | Tech                                                                    |
|-----------|-------------------------------------------------------------------------|
| Backend   | FastAPI, SQLModel/SQLite, [ansible-runner](https://ansible.readthedocs.io/projects/runner/), Authlib |
| Frontend  | React + TypeScript (Vite), no UI framework, mobile-first CSS             |
| Playbooks | Starter playbooks shipped in the image, persisted in an editable bind-mounted directory |
| Deploy    | Single Docker container via Docker Compose                              |

HTTP clients (Proxmox API, release checks and Authlib OIDC) use `httpx2`; the FastAPI/Starlette
test client uses the same transport dependency.

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
picker), or drop a `.yml` file into the bind-mounted `playbooks/` directory.
The first play's `name` is used as the title, the leading `#` comment
block as the description, and the play-level `vars:` as the defaults that are prefilled when running.

The editor validates before saving, in three stages, and reports issues with line numbers (tap one to jump to the line):

1. **YAML** syntax (Ansible tags such as `!vault` are accepted)
2. **Structure**: a list of plays, each with `hosts` (or `import_playbook`). Warnings for plays that don't target `all`
   (the app only puts the selected hosts into the inventory) or have no tasks
3. **`ansible-playbook --syntax-check`**, run inside the selected source folder so relative `tasks/`, `vars/` and `templates/` resolve.
   This catches unknown modules, invalid keywords and missing includes

Files with errors are not saved. Every save or delete keeps the previous version in `data/playbook-history/<file>/` (last 20).
Top-level playbook files in each source can be edited in the UI; `tasks/`, `templates/` and `vars/` are managed on disk.
New playbooks default to the local root; use `sources/<source>/<file>.yml` as the filename to create one in an existing source.

### Multiple playbook sources and updates

All sources appear together on Run, Manage playbooks and Schedules. Paths include the source name, so
`custom.yml`, `sources/team-a/custom.yml` and `sources/team-b/custom.yml` are separate selectable playbooks.
Each playbook runs and validates inside its own source folder, preserving relative tasks, vars, templates,
roles and imported playbooks. Supporting task files are not listed as runnable playbooks.

- **Local files:** place playbooks directly in `./playbooks`, or add any number of folders under
  `./playbooks/sources/<name>`. Sources are discovered automatically on catalog requests.
- **Additional local bind mounts:** add `"/host/path:/playbooks/sources/<name>"` to the Compose service's
  volumes. Use names containing letters, digits, `_`, `-` or `.` (starting with a letter/digit, max 64 characters).
  Mount writable directories: the entrypoint needs permission to set ownership.
  Do not use symbolic links as source folders.
- **Git sources:** add multiple repositories from the first-run wizard or **Settings → Playbooks**.
  Use a unique source name, an unauthenticated HTTPS URL (or HTTP for a local Git server), optional branch/tag,
  and the repository's playbook folder. HTTP is unencrypted. Imports live under `./playbooks/sources/<name>`
  and never replace local files or other repositories. Re-adding the same URL/ref/folder is idempotent.
- **Pull updates:** click **Pull latest** on a Git source and confirm. Palma fetches the current contents of
  its configured branch/tag without rebuilding or updating the Docker image. An empty ref follows the upstream
  default branch; a fixed tag stays pinned. The source snapshot is replaced, including supporting files and
  upstream deletions. Local edits in that Git source are overwritten after a backup is saved under
  `./data/playbook-backups/<repository-id>/<backup-id>/`. Other Git sources and local files are unchanged.
  Failed downloads leave the existing snapshot intact; replacement failures restore the previous snapshot.
  Wait for active runs to finish and disable schedules using that source before pulling; review new versions
  and re-enable schedules afterwards. Dependencies/collections still need to be available in the image.
  Updates are manual, not scheduled automatic pulls.

Fresh instances seed bundled starter playbooks into `sources/palma`, registered as the default Git source,
so **Pull latest** also updates Palma's own playbooks independently of the image.
Existing root playbooks keep their filenames and remain local. If upgrading from the previous single-repository
setup, its metadata is retained; its first pull creates a new `sources/legacy-<id>` source without deleting root
files. Use the new namespaced paths (including in schedules) for updated versions.

## Deployment (Docker Compose)

```bash
docker compose up -d
```

Only `docker-compose.yml` and Docker Engine/Desktop with Compose **2.24 or newer** are needed.
No checkout, `.env`, pre-created host directories, SSH tools or host Ansible installation is required.
Compose creates `./data`, `./playbooks` and `./ssh` next to the Compose file automatically.
The container seeds starter playbooks into `./playbooks/sources/palma` when `./playbooks` is empty on first startup and fixes directory/key
permissions. Existing playbooks are never overwritten; after initialization, deleting playbooks does not
cause them to be restored automatically.
Open `http://<docker-host>:8080` to start the wizard:

1. **Authentication**: choose a local administrator account (password of at least 12 characters, stored as a
   salted scrypt hash) or **OIDC / Authentik**. The OIDC option provides provider instructions and fields for
   issuer, client ID/secret, public URL and optional allowed groups. Register both
   `<PUBLIC_URL>/auth/setup-callback` and `<PUBLIC_URL>/auth/callback` with the provider.
   Successful OIDC sign-in activates the configuration and resumes the SSH step; no local password is required.
   Failed sign-in leaves configuration pending so the same browser can retry or choose local login.
   Use the same public URL throughout setup and an HTTPS issuer.
2. **SSH keypair**: generate an Ed25519 controller key inside the container, or reuse a supplied unencrypted
   private key. Copy the public key and install it on managed hosts, or use **Install SSH key** after adding hosts.
3. **Playbook sources**: defaults to `https://github.com/mrgamewatch/palma.git`, using the starter files
   bundled into the image without a network request. Add more Git repositories (HTTPS or local HTTP) and/or
   bind-mounted local folders. All sources are merged, with source labels for duplicate filenames.
   Local-only setups are supported. Sources can be added and Git snapshots updated later under **Settings → Playbooks**.
   Only import repositories you trust; custom playbooks must use collections available in the image.
4. **Proxmox (optional)**: follow the on-screen user/token/permission, guest-agent and SSH requirements,
   test the connection and save the source, or **Skip and finish**. Add sources later on the Proxmox tab.
   After saving, use **Discover guests** to choose which hosts to import.

Setup progress and completion are persisted. After a restart, login resumes unfinished setup; completed
instances open the normal UI. Data (including account and generated session secret), playbooks and SSH keys
live in bind-mounted `./data`, `./playbooks` and `./ssh` directories.
Recreating the container or running `docker compose down -v` preserves these host directories.
Back up these directories: they include private keys and Proxmox token secrets.
Wizard OIDC settings (including client secret) are stored in `./data/oidc.json` with owner-only permissions,
not in browser cookies or public API responses. Complete environment OIDC settings take precedence.
Pending OIDC configuration is in `./data/oidc-pending.json` and reserved to the configuring browser.
If that browser session is lost before activation, stop Palma, remove only `oidc-pending.json`, and restart
to retry authentication setup. Do not delete the data directory.

**Claim a fresh instance on a trusted network before exposing it publicly.** The first visitor can create the
administrator. Use an HTTPS reverse proxy for remote access. For optional configuration, put environment
variables in the service's `environment:` block or use a `.env` file (see `.env.example`); neither is required.
`PORT` defaults to 8080 and `BIND_ADDRESS` to `0.0.0.0`.

To supply an existing key, add an optional read-only volume mount such as
`/path/to/existing/ssh:/ssh-keys:ro`, or set `SSH_KEY_DIR` to an existing directory to use it directly.
The entrypoint applies strict permissions to the persistent SSH directory.
The default private-key filename is `id_ed25519`; set `SSH_KEY_PATH` for a different filename.

**Existing installations:** keep the Compose file in the same directory to reuse the existing `./data`,
`./playbooks` and `./ssh` bind mounts. `SSH_KEY_DIR` remains supported; its directory is now mounted
directly at `/home/app/.ssh` so generated keys persist too. Back up your directories before upgrading.
Existing environment-based local/OIDC logins remain supported.

### Prebuilt image

Multi-arch images (`linux/amd64`, `linux/arm64`) are published to the GitHub Container Registry by
[GitHub Actions](.github/workflows/docker.yml):

| Tag | Built from |
|-----|------------|
| `latest`, `1.2.3`, `1.2`, `1` | release tags `v1.2.3` |
| `edge` | every push to `main` |
| `sha-<commit>` | every push |

Compose uses the prebuilt image by default:

```yaml
    image: ghcr.io/mrgamewatch/palma:latest
```

Update with `docker compose pull && docker compose up -d`. No repository checkout is needed.
The first-run wizard requires an image release containing this feature; older published tags still use the
old startup behavior. To test unpublished local changes from a checkout:

```bash
docker build -t ghcr.io/mrgamewatch/palma:latest .
docker compose up -d --pull never
```

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
| otherwise, `ADMIN_PASSWORD` set or wizard account exists | Local login page |
| neither                             | First-run administrator creation |

### Authentik

1. In Authentik, go to **Applications → Applications → Create with provider** and choose **OAuth2/OpenID Provider**.
   - Client type: *Confidential*
   - Redirect URI: `<PUBLIC_URL>/auth/callback` (e.g. `http://192.168.1.10:8080/auth/callback`)
   - Scopes: `openid`, `email`, `profile` (default mappings)
2. Copy the client ID and secret into `.env`. Set `OIDC_ISSUER` to the provider's *OpenID Configuration Issuer*
   (e.g. `https://auth.example.com/application/o/palma/`).
3. Optional: set `OIDC_ALLOWED_GROUPS` (comma separated) to restrict access, and/or bind the application to a group in Authentik.
4. `SESSION_SECRET` is generated and persisted automatically if unset (you may supply your own).
   Behind an HTTPS reverse proxy, also set `SESSION_HTTPS_ONLY=true`
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

Use the requirements guide in the setup wizard or the **Add Proxmox source** sheet. Create a dedicated user
(e.g. `palma@pve`) and grant **PVEAuditor** on `/` with propagation. Create an API token for it with privilege
separation enabled and grant that token **PVEAuditor** on `/` with propagation too: effective permissions are
the intersection of user and token permissions. Copy the one-time token secret and add it in the wizard or
on the **Proxmox** tab, then tap **Discover guests** and import the containers and VMs you want.

- **LXC**: the IP comes from the container's interfaces when it's running; otherwise from a static `ip=` in `net0`.
- **VMs**: the IP comes from the **QEMU guest agent** (`qemu-guest-agent` installed in the VM and *QEMU Guest Agent*
  enabled in the VM options; the token needs `VM.GuestAgent.Audit` on PVE 9, which PVEAuditor includes, or
  `VM.Monitor` on PVE 8). Otherwise it comes from a cloud-init `ipconfig0`. Docker/bridge interfaces are ignored.
  Windows VMs are listed but not imported, and templates are hidden.
- Guests without an IP show the reason. Re-importing refreshes the IP, node, status and type. Imported hosts are
  tagged `proxmox`, `<source name>` and any Proxmox tags, and get the type `lxc` or `vm`.

> The Proxmox token secret is stored in the SQLite database in `./data`. Protect and back up that directory.

## Development

### Containerized tests and validation

With Docker Desktop running in Linux-container mode (or Docker Engine with Compose), run from the repository root:

```bash
sh test.sh
# Equivalent Docker command:
docker compose -f docker-compose.tests.yml run --build --rm validation
```

This builds/type-checks the frontend, runs the backend pytest suite, and validates every starter playbook
using the editor's YAML/structure checks and `ansible-playbook --syntax-check`. Dependencies use the
existing pinned requirements and lockfile. Image builds need internet access; the test container has
no network, host mounts, published ports, SSH keys, production environment file, or Docker socket.
SSSD validation uses a temporary copy of the checked-in example variables, not real LDAP credentials.
Tests operate on copies of the playbooks and temporary databases.

For a syntax check of just one playbook, without building the frontend or installing backend/test
dependencies:

```bash
sh test.sh --playbook safe_reboot.yml
```

This uses a separate Docker build target with only the pinned Ansible version and required collections.
It skips Node/npm, the frontend build, backend code/dependencies, pytest and OS package installation.
Pass a top-level playbook filename (not a path). The playbook directory is copied to preserve relative
includes; SSSD uses example variables. This mode performs Ansible syntax checking only, not the editor
tests, module argument validation, or execution on a target device.

To run playbook validation and editor tests using the full test image:

```bash
sh test.sh tests/test_playbook_editor.py
```

`test.sh` works from any directory and, except in `--playbook` mode, forwards all arguments to pytest, for example
`sh /path/to/palma/test.sh -k safe_reboot`. Use a POSIX shell on Linux/macOS or Git Bash/WSL on Windows.

Rebuilds reuse cached dependency/frontend layers. A nonzero exit code means validation failed.
These checks never reboot a device and do not prove recovery on real LXC, Proxmox or bare-metal targets;
test that separately on disposable devices. The parametrized playbook checks also run in the existing CI backend job.

### Local development

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
