"""Discovers playbooks in the playbooks directory and extracts a title/description."""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import get_settings

EXCLUDED = {"requirements.yml", "requirements.yaml"}
SOURCE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


@dataclass
class PlaybookInfo:
    path: str
    title: str
    description: str
    vars: dict[str, Any] = field(default_factory=dict)
    source: str = "local"

    def dict(self) -> dict:
        return asdict(self)


def _leading_comment(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "---" and not lines:
            continue
        if not stripped.startswith("#"):
            break
        lines.append(stripped.lstrip("#").strip())
    return "\n".join(lines).strip()


def _default_vars(play: dict) -> dict[str, Any]:
    """Play-level vars are the playbook's documented defaults; templated values are internal and skipped."""
    raw = play.get("vars")
    if not isinstance(raw, dict):
        return {}
    defaults: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or "{{" in json.dumps(value, default=str) or "{%" in json.dumps(value, default=str):
            continue
        defaults[key] = json.loads(json.dumps(value, default=str))
    return defaults


def _parse(path: Path, root: Path) -> PlaybookInfo | None:
    try:
        text = path.read_text(encoding="utf-8")
        from .playbook_editor import AnsibleLoader

        data = yaml.load(text, Loader=AnsibleLoader)  # noqa: S506 - SafeLoader subclass
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    if not any(isinstance(p, dict) and ("hosts" in p or "import_playbook" in p) for p in data):
        return None
    title = data[0].get("name") or path.stem
    return PlaybookInfo(
        path=path.relative_to(root).as_posix(),
        title=title,
        description=_leading_comment(text),
        vars=_default_vars(data[0]),
    )


def list_playbooks(root: Path | None = None) -> list[PlaybookInfo]:
    catalog = root is None
    root = (root if root is not None else get_settings().playbooks_dir).resolve()
    if not root.is_dir():
        return []
    found = []
    folders = [("local", root)]
    if catalog:
        folders.extend(source_folders(root))
    for label, folder in folders:
        for path in sorted([*folder.glob("*.yml"), *folder.glob("*.yaml")]):
            if path.name in EXCLUDED or path.name.startswith(".") or path.is_symlink():
                continue
            info = _parse(path, root)
            if info:
                info.source = label
                found.append(info)
    return found


def source_folders(root: Path | None = None) -> list[tuple[str, Path]]:
    root = root if root is not None else get_settings().playbooks_dir.resolve()
    sources = root / "sources"
    if not sources.is_dir() or sources.is_symlink():
        return []
    return [
        (folder.name, folder) for folder in sorted(sources.iterdir())
        if SOURCE_NAME_RE.fullmatch(folder.name) and folder.is_dir() and not folder.is_symlink()
    ]


def resolve_playbook(rel_path: str) -> Path:
    """Returns the absolute path of a known playbook, rejecting anything outside the catalog."""
    known = {p.path for p in list_playbooks()}
    if rel_path not in known:
        raise FileNotFoundError(rel_path)
    return get_settings().playbooks_dir.resolve() / rel_path
