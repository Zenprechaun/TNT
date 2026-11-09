#!/usr/bin/env bash
# Copies the live database into /srv/tahoetable/backups and removes copies older than 14 days.
# Runs every night (see /etc/cron.d/tahoetable-backup) and before each update.
set -euo pipefail

ROOT="/srv/tahoetable"
DB="$ROOT/data/db.sqlite3"
TARGET="$ROOT/backups/db-$(date +%Y-%m-%d-%H%M%S).sqlite3"

# Work from a folder this account can open, whatever folder it was started from.
cd "$ROOT"

if [[ ! -f "$DB" ]]; then
  echo "There's no database to back up yet."
  exit 0
fi

# SQLite's own backup method makes a consistent copy even while the site is running.
"$ROOT/venv/bin/python" - "$DB" "$TARGET" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
target.close()
source.close()
PY

find "$ROOT/backups" -name 'db-*.sqlite3' -mtime +14 -delete
echo "Saved $TARGET"
