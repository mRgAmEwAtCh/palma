#!/usr/bin/env python3
"""Finds newer release tags for image tags pinned via variables in a Compose stack's .env file.

Run on the target host by docker_compose_update.yml (tasks/compose_project.yml). Read-only: it prints a JSON
report, the playbook applies the changes. Standard library only, so it works on any host Ansible manages.

Input (argv[1], base64-encoded JSON):
  {"project": "authentik", "dir": "/opt/authentik", "allow_override": "",
   "rules": [{"var": "AUTHENTIK_TAG", "allow": "patch"}]}

Output (stdout, JSON):
  {"updates": [{"var", "current", "target", "images"}], "notes": ["..."]}

Version levels follow semver positions: for 2026.8.5, "2026" is major, "8" minor, "5" patch.
  patch -> 2026.8.x, minor -> 2026.x.y, major -> any newer version. Pre-releases (e.g. -rc1) are ignored.
"""

import base64
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

LEVELS = ("none", "patch", "minor", "major")
VERSION_RE = re.compile(r"(v?)(\d+(?:\.\d+)*)")
TIMEOUT = 20
MAX_PAGES = 50


def read_env(path):
    """Parses KEY=VALUE lines of a .env file (comments, blank lines and 'export ' prefixes allowed)."""
    values = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                key, _, value = line.partition("=")
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                values[key.strip()] = value
    except FileNotFoundError:
        pass
    return values


def parse_version(tag):
    """'2026.8.5' -> ('', (2026, 8, 5)); 'v1.2' -> ('v', (1, 2)); non-versions -> None."""
    m = VERSION_RE.fullmatch(tag or "")
    if not m:
        return None
    return m.group(1), tuple(int(p) for p in m.group(2).split("."))


def is_allowed(current, candidate, level):
    """True if candidate is newer than current and stays within the allowed level."""
    if candidate <= current or len(candidate) != len(current):
        return False
    if level == "patch":
        return candidate[:2] == current[:2]
    if level == "minor":
        return candidate[:1] == current[:1]
    return level == "major"


def classify(current, candidate):
    if candidate[:1] != current[:1]:
        return "major"
    if candidate[:2] != current[:2]:
        return "minor"
    return "patch"


def select(current_tag, available_tags, level):
    """Returns (target_tag or None, newest_tag or None) among tags with the same shape as current_tag."""
    current = parse_version(current_tag)
    if current is None:
        return None, None
    prefix, cur = current
    candidates = {}
    for tag in available_tags:
        parsed = parse_version(tag)
        if parsed and parsed[0] == prefix and len(parsed[1]) == len(cur) and parsed[1] > cur:
            candidates[parsed[1]] = tag
    if not candidates:
        return None, None
    newest = candidates[max(candidates)]
    allowed = [v for v in candidates if is_allowed(cur, v, level)]
    return (candidates[max(allowed)] if allowed else None), newest


def split_image(image):
    """'ghcr.io/goauthentik/server:2026.8.5' -> ('ghcr.io/goauthentik/server', '2026.8.5')."""
    image = image.split("@", 1)[0]
    name, _, tag = image.rpartition(":")
    if not name or "/" in tag:
        return image, "latest"
    return name, tag


def project_images(project):
    out = subprocess.run(
        ["docker", "ps", "--all", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.Image}}"],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def registry_endpoint(repo):
    """Maps an image repository to (registry host, repository path) for the Registry v2 API."""
    first, _, rest = repo.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        host, path = first, rest
    else:
        host, path = "docker.io", repo
    if host in ("docker.io", "index.docker.io"):
        host = "registry-1.docker.io"
        if "/" not in path:
            path = f"library/{path}"
    return host, path


def _bearer_token(challenge):
    params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    if "realm" not in params:
        return None
    query = urllib.parse.urlencode({k: v for k, v in params.items() if k in ("service", "scope")})
    with urllib.request.urlopen(f"{params['realm']}?{query}", timeout=TIMEOUT) as r:
        data = json.load(r)
    return data.get("token") or data.get("access_token")


def list_tags(repo):
    """All tags of an image repository (anonymous access, follows pagination)."""
    host, path = registry_endpoint(repo)
    url = f"https://{host}/v2/{path}/tags/list?n=1000"
    token, tags = None, []
    for _ in range(MAX_PAGES):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as r:
                tags += json.load(r).get("tags") or []
                link = r.headers.get("Link", "")
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and token is None:
                token = _bearer_token(exc.headers.get("WWW-Authenticate", ""))
                if token:
                    continue
            raise
        m = re.search(r"<([^>]+)>;\s*rel=\"next\"", link)
        if not m:
            return tags
        url = urllib.parse.urljoin(f"https://{host}", m.group(1))
    return tags


def check_rule(project, env, rule, allow_override):
    var = rule["var"]
    level = (allow_override or rule.get("allow") or "patch").lower()
    if level not in LEVELS:
        return None, f"{var}: unknown allow level '{level}' (use {', '.join(LEVELS)})"
    if var not in env:
        return None, None
    current = env[var]
    if parse_version(current) is None:
        return None, f"{var}={current} is not a version tag, skipped"

    repos = sorted({repo for repo, tag in map(split_image, project_images(project)) if tag == current})
    if not repos:
        return None, f"{var}={current}: no container of the stack uses this tag, skipped"

    tag_sets = []
    for repo in repos:
        try:
            tag_sets.append(set(list_tags(repo)))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return None, f"{var}: could not list tags of {repo}: {exc}"
    common = set.intersection(*tag_sets)  # every image using the variable must have the new tag
    target, newest = select(current, common, level)

    note = None
    if newest and newest != target:
        kind = classify(parse_version(current)[1], parse_version(newest)[1])
        hint = f"; run with compose_tag_allow={kind} to apply" if LEVELS.index(kind) > LEVELS.index(level) else ""
        note = f"{var}: {newest} available ({kind} update, not applied with allow={level}{hint})"
    if target is None:
        return None, note or f"{var}={current} is up to date"
    update = {"var": var, "current": current, "target": target, "images": repos}
    return update, note


def main():
    payload = json.loads(base64.b64decode(sys.argv[1]))
    env = read_env(f"{payload['dir']}/.env")
    report = {"updates": [], "notes": []}
    for rule in payload.get("rules") or []:
        try:
            update, note = check_rule(payload["project"], env, rule, payload.get("allow_override") or "")
        except subprocess.SubprocessError as exc:
            update, note = None, f"{rule.get('var')}: docker query failed: {exc}"
        if update:
            report["updates"].append(update)
        if note:
            report["notes"].append(note)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
