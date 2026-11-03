import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "playbooks" / "files" / "compose_tag_check.py"
_spec = importlib.util.spec_from_file_location("compose_tag_check", _PATH)
ctc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ctc)

AUTHENTIK_TAGS = [
    "2026.5.7", "2026.5.8", "2026.8.0", "2026.8.4", "2026.8.5", "2026.8.6", "2026.8.7-rc1",
    "2026.11.0", "2026.11.1", "2027.2.0", "2026.8", "latest", "gh-main", "2026.8.6-arm64",
]


def test_read_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\n\nAUTHENTIK_TAG="2026.8.5"\nexport PG_TAG=16\nEMPTY=\nQ=\'x y\'\n')
    assert ctc.read_env(str(env)) == {"AUTHENTIK_TAG": "2026.8.5", "PG_TAG": "16", "EMPTY": "", "Q": "x y"}
    assert ctc.read_env(str(tmp_path / "missing")) == {}


@pytest.mark.parametrize(
    "tag,expected",
    [("2026.8.5", ("", (2026, 8, 5))), ("v1.2", ("v", (1, 2))), ("16-alpine", None), ("latest", None), ("", None)],
)
def test_parse_version(tag, expected):
    assert ctc.parse_version(tag) == expected


@pytest.mark.parametrize(
    "current,level,expected",
    [
        ("2026.8.5", "patch", ("2026.8.6", "2027.2.0")),  # rc and suffixed tags ignored
        ("2026.8.5", "minor", ("2026.11.1", "2027.2.0")),
        ("2026.8.5", "major", ("2027.2.0", "2027.2.0")),
        ("2026.8.5", "none", (None, "2027.2.0")),
        ("2027.2.0", "major", (None, None)),  # up to date
        ("2026.8", "patch", (None, "2027.2")),  # floating tag: same-shape candidates only, none allowed for patch
    ],
)
def test_select(current, level, expected):
    tags = AUTHENTIK_TAGS + (["2027.2"] if current == "2026.8" else [])
    assert ctc.select(current, tags, level) == expected


def test_select_keeps_v_prefix():
    assert ctc.select("v1.2.3", ["1.2.9", "v1.2.4", "v1.3.0"], "patch") == ("v1.2.4", "v1.3.0")


@pytest.mark.parametrize(
    "image,expected",
    [
        ("ghcr.io/goauthentik/server:2026.8.5", ("ghcr.io/goauthentik/server", "2026.8.5")),
        ("localhost:5000/app", ("localhost:5000/app", "latest")),
        ("postgres", ("postgres", "latest")),
        ("redis:7@sha256:abc", ("redis", "7")),
    ],
)
def test_split_image(image, expected):
    assert ctc.split_image(image) == expected


@pytest.mark.parametrize(
    "repo,expected",
    [
        ("ghcr.io/goauthentik/server", ("ghcr.io", "goauthentik/server")),
        ("postgres", ("registry-1.docker.io", "library/postgres")),
        ("docker.io/library/postgres", ("registry-1.docker.io", "library/postgres")),
        ("bitnami/redis", ("registry-1.docker.io", "bitnami/redis")),
        ("localhost:5000/app", ("localhost:5000", "app")),
    ],
)
def test_registry_endpoint(repo, expected):
    assert ctc.registry_endpoint(repo) == expected


@pytest.fixture()
def registry(monkeypatch):
    images = {"authentik": ["ghcr.io/goauthentik/server:2026.8.5", "postgres:16-alpine"]}
    tags = {"ghcr.io/goauthentik/server": AUTHENTIK_TAGS}
    monkeypatch.setattr(ctc, "project_images", lambda project: images[project])
    monkeypatch.setattr(ctc, "list_tags", lambda repo: tags[repo])
    return images, tags


def test_check_rule_patch_with_note(registry):
    update, note = ctc.check_rule("authentik", {"AUTHENTIK_TAG": "2026.8.5"}, {"var": "AUTHENTIK_TAG", "allow": "patch"}, "")
    assert update == {"var": "AUTHENTIK_TAG", "current": "2026.8.5", "target": "2026.8.6",
                      "images": ["ghcr.io/goauthentik/server"]}
    assert note == ("AUTHENTIK_TAG: 2027.2.0 available (major update, not applied with allow=patch; "
                    "run with compose_tag_allow=major to apply)")


def test_check_rule_override_and_up_to_date(registry):
    images, _ = registry
    rule = {"var": "AUTHENTIK_TAG", "allow": "patch"}
    update, _ = ctc.check_rule("authentik", {"AUTHENTIK_TAG": "2026.8.5"}, rule, "major")
    assert update["target"] == "2027.2.0"
    images["authentik"] = ["ghcr.io/goauthentik/server:2027.2.0"]
    assert ctc.check_rule("authentik", {"AUTHENTIK_TAG": "2027.2.0"}, rule, "") == (None, "AUTHENTIK_TAG=2027.2.0 is up to date")


def test_check_rule_skips(registry):
    rule = {"var": "AUTHENTIK_TAG", "allow": "patch"}
    assert ctc.check_rule("authentik", {}, rule, "") == (None, None)
    assert "not a version" in ctc.check_rule("authentik", {"AUTHENTIK_TAG": "latest"}, rule, "")[1]
    assert "no container" in ctc.check_rule("authentik", {"AUTHENTIK_TAG": "2026.8.4"}, rule, "")[1]
    assert "unknown allow level" in ctc.check_rule("authentik", {"AUTHENTIK_TAG": "2026.8.5"}, rule, "bogus")[1]


def test_check_rule_requires_tag_in_all_images(registry):
    images, tags = registry
    images["authentik"].append("ghcr.io/goauthentik/ldap:2026.8.5")
    tags["ghcr.io/goauthentik/ldap"] = ["2026.8.5"]  # ldap image has no 2026.8.6 yet
    update, note = ctc.check_rule("authentik", {"AUTHENTIK_TAG": "2026.8.5"}, {"var": "AUTHENTIK_TAG", "allow": "patch"}, "")
    assert update is None and note == "AUTHENTIK_TAG=2026.8.5 is up to date"


def test_playbook_defaults_watch_authentik():
    from app.playbooks import list_playbooks

    pb = {p.path: p for p in list_playbooks()}["docker_compose_update.yml"]
    assert pb.vars["compose_tag_updates"] == [{"var": "AUTHENTIK_TAG", "allow": "patch"}]
    assert pb.vars["compose_tag_allow"] == ""
