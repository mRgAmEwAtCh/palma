#!/bin/sh
# Copies mounted SSH keys with strict permissions (ssh refuses world-readable keys),
# fixes ownership of the data and playbooks dirs (playbooks are editable in the UI),
# then drops privileges to the "app" user.
set -e

mkdir -p /data /playbooks /home/app/.ssh
if [ ! -f /data/playbooks-initialized ]; then
  if [ -z "$(find /playbooks -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    mkdir -p /playbooks/sources/palma
    cp -R /app/default-playbooks/. /playbooks/sources/palma/
    touch /playbooks/sources/palma/.palma-bundled
  fi
  touch /data/playbooks-initialized
fi
if [ -d /ssh-keys ]; then
  for f in /ssh-keys/*; do
    if [ -f "$f" ]; then
      cp "$f" /home/app/.ssh/
    fi
  done
fi
chmod 700 /home/app/.ssh
find /home/app/.ssh -type f -exec chmod 600 {} +
find /home/app/.ssh -type f -name '*.pub' -exec chmod 644 {} +
chown -R app:app /home/app /data
[ -d /playbooks ] && chown -R app:app /playbooks

exec setpriv --reuid=app --regid=app --init-groups "$@"
