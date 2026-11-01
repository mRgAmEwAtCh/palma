#!/bin/sh
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"

if [ "${1:-}" = "--playbook" ]; then
  if [ "$#" -ne 2 ]; then
    printf '%s\n' "Usage: sh test.sh --playbook <filename.yml>" >&2
    exit 2
  fi
  case "$2" in
    */*|requirements.yml|requirements.yaml|.*)
      printf '%s\n' "Use a top-level playbook filename, not a path or collection requirements." >&2
      exit 2
      ;;
    *.yml|*.yaml) ;;
    *)
      printf '%s\n' "Playbook filename must end in .yml or .yaml." >&2
      exit 2
      ;;
  esac
  if [ ! -f "playbooks/$2" ]; then
    printf 'Playbook not found: %s\n' "$2" >&2
    exit 2
  fi
  exec docker compose -f docker-compose.tests.yml run --build --rm playbook-validation "./$2"
fi

exec docker compose -f docker-compose.tests.yml run --build --rm validation \
  python -m pytest -q "$@"
