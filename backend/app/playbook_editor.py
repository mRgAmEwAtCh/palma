"""Validation, saving and deletion of playbooks edited in the UI."""

import os
import re
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import get_settings

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.ya?ml$")
RESERVED = {"requirements.yml", "requirements.yaml"}
HISTORY_KEEP = 20
SYNTAX_CHECK_TIMEOUT = 60


class AnsibleLoader(yaml.SafeLoader):
    """SafeLoader that tolerates Ansible-specific tags such as !vault or !unsafe."""


def _any_tag(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


AnsibleLoader.add_multi_constructor("!", _any_tag)


@dataclass
class Issue:
    message: str
    source: str  # yaml | structure | ansible
    line: int | None = None
    column: int | None = None


@dataclass
class ValidationResult:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def dict(self) -> dict:
        return {"valid": self.valid, "errors": [asdict(i) for i in self.errors], "warnings": [asdict(i) for i in self.warnings]}


class PlaybookFileError(ValueError):
    pass


def playbooks_root() -> Path:
    return get_settings().playbooks_dir.resolve()


def check_name(name: str) -> Path:
    """Only plain top-level playbook file names are allowed (no paths)."""
    if not NAME_RE.match(name or "") or name.lower() in RESERVED:
        raise PlaybookFileError(
            "Invalid file name: use letters, digits, '-', '_' or '.', ending in .yml/.yaml (no folders)"
        )
    return playbooks_root() / name


def _yaml_issue(exc: yaml.YAMLError) -> Issue:
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    problem = getattr(exc, "problem", None) or str(exc)
    context = getattr(exc, "context", None)
    message = f"{problem} ({context})" if context and context not in problem else problem
    return Issue(message=message, source="yaml", line=mark.line + 1 if mark else None, column=mark.column + 1 if mark else None)


def _check_structure(content: str, result: ValidationResult) -> bool:
    try:
        data = yaml.load(content, Loader=AnsibleLoader)  # noqa: S506 - SafeLoader subclass
        node = yaml.compose(content, Loader=AnsibleLoader)
    except yaml.YAMLError as exc:
        result.errors.append(_yaml_issue(exc))
        return False

    if data is None:
        result.errors.append(Issue("The playbook is empty", "structure", 1, 1))
        return False
    if not isinstance(data, list):
        result.errors.append(
            Issue("A playbook must be a list of plays (start with '- name: ...' / '  hosts: all')", "structure", 1, 1)
        )
        return False

    items = node.value if isinstance(node, yaml.SequenceNode) else []
    for i, play in enumerate(data):
        line = items[i].start_mark.line + 1 if i < len(items) else None
        label = f"Play {i + 1}"
        if not isinstance(play, dict):
            result.errors.append(Issue(f"{label} must be a mapping (key: value pairs)", "structure", line, 1))
            continue
        if "import_playbook" in play:
            continue
        label = f"Play '{play.get('name')}'" if play.get("name") else label
        if "hosts" not in play:
            result.errors.append(Issue(f"{label} has no 'hosts' (use 'hosts: all')", "structure", line, 1))
            continue
        if i == 0 and not play.get("name"):
            result.warnings.append(Issue("The first play has no 'name'; the file name is shown as title", "structure", line, 1))
        if str(play.get("hosts")).strip() != "all":
            result.warnings.append(
                Issue(
                    f"{label} targets '{play.get('hosts')}'. The app only puts the selected hosts into the inventory "
                    "(groups = tags and types); use 'hosts: all' to run on every selected host",
                    "structure",
                    line,
                    1,
                )
            )
        if not any(k in play for k in ("tasks", "roles", "pre_tasks", "post_tasks", "handlers")):
            result.warnings.append(Issue(f"{label} has no tasks or roles", "structure", line, 1))
    return True


_ORIGIN_RE = re.compile(r"Origin: .*?:(\d+)(?::(\d+))?")
_LEGACY_POS_RE = re.compile(r"line (\d+), column (\d+)")


def _ansible_issue(output: str, temp_name: str, display_name: str) -> Issue:
    text = output.replace(temp_name, display_name).replace(f"{playbooks_root()}/", "")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("[WARNING]")]
    message_lines: list[str] = []
    for ln in lines:
        if ln.startswith("Origin:") or re.match(r"^\s*\d+\s", ln) or ln.strip().startswith("^"):
            break
        message_lines.append(ln.replace("[ERROR]: ", "").replace("ERROR! ", "").strip())
    line = column = None
    if m := _ORIGIN_RE.search(text) or _LEGACY_POS_RE.search(text):
        line = int(m.group(1))
        column = int(m.group(2)) if m.group(2) else None
    message = " ".join(message_lines).strip() or "ansible-playbook --syntax-check failed"
    return Issue(message=message[:1000], source="ansible", line=line, column=column)


def _ansible_syntax_check(content: str, display_name: str, result: ValidationResult) -> None:
    root = playbooks_root()
    temp_name = f".validate-{uuid.uuid4().hex}.yml"
    try:
        # Inside the playbooks dir so relative tasks/, vars/ and templates/ paths resolve like in a real run.
        temp = root / temp_name
        temp.write_text(content, encoding="utf-8")
    except OSError:
        import tempfile

        temp = Path(tempfile.gettempdir()) / temp_name
        temp.write_text(content, encoding="utf-8")
        result.warnings.append(
            Issue("Playbooks folder is read-only; relative includes could not be checked", "ansible")
        )
    try:
        env = {**os.environ, "ANSIBLE_NOCOLOR": "1", "ANSIBLE_DEPRECATION_WARNINGS": "False", "ANSIBLE_FORCE_COLOR": "0"}
        r = subprocess.run(
            ["ansible-playbook", "--syntax-check", "-i", "localhost,", str(temp)],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=SYNTAX_CHECK_TIMEOUT,
        )
        if r.returncode != 0:
            result.errors.append(_ansible_issue(r.stderr + "\n" + r.stdout, str(temp), display_name))
    except subprocess.TimeoutExpired:
        result.errors.append(Issue("ansible-playbook --syntax-check timed out", "ansible"))
    except OSError as exc:
        result.warnings.append(Issue(f"Ansible syntax check unavailable: {exc}", "ansible"))
    finally:
        temp.unlink(missing_ok=True)


def validate(content: str, name: str = "playbook.yml") -> ValidationResult:
    result = ValidationResult()
    if _check_structure(content, result) and not result.errors:
        _ansible_syntax_check(content, name, result)
    return result


def _history_dir(name: str) -> Path:
    return get_settings().data_dir / "playbook-history" / name


def _archive(path: Path, suffix: str = "") -> None:
    if not path.exists():
        return
    folder = _history_dir(path.name)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    shutil.copy2(path, folder / f"{stamp}{suffix}.yml")
    for old in sorted(folder.iterdir())[:-HISTORY_KEEP]:
        old.unlink(missing_ok=True)


def save(name: str, content: str, create: bool) -> ValidationResult:
    path = check_name(name)
    if create and path.exists():
        raise PlaybookFileError(f"'{name}' already exists")
    if not create and not path.exists():
        raise FileNotFoundError(name)
    if not content.endswith("\n"):
        content += "\n"
    result = validate(content, name)
    if not result.valid:
        return result
    _archive(path)
    temp = path.with_name(f".{name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)
    return result


def delete(name: str) -> None:
    path = check_name(name)
    if not path.exists():
        raise FileNotFoundError(name)
    _archive(path, "-deleted")
    path.unlink()
