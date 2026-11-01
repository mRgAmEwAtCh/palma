#!/bin/sh
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"

exec docker compose -f docker-compose.tests.yml run --build --rm validation \
  python -m pytest -q "$@"
