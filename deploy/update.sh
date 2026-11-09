#!/usr/bin/env bash
# Puts a new version of the website live on the Hostinger VPS.
#
# Automatic publishing (deploy/publish.sh) runs this for every new version on GitHub.
# To update by hand instead, upload the new project zip to the server, unzip it, then run
# this as root:
#     bash tahoe-neighborhood-table/deploy/update.sh
#
# The database, the settings file (/srv/tahoetable/.env) and the HTTPS setup stay as they are.
set -euo pipefail

APP_USER="tahoetable"
ROOT="/srv/tahoetable"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n==> %s\n' "$1"; }
as_app() { sudo -u "$APP_USER" "$@"; }

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root, for example: sudo bash $0" >&2
  exit 1
fi
if [[ ! -d "$ROOT/app" || ! -f "$ROOT/.env" ]]; then
  echo "The website isn't set up on this server yet. Run deploy/setup_server.sh first." >&2
  exit 1
fi

say "Backing up the database"
as_app "$ROOT/backup_db.sh"

if [[ "$SRC" != "$ROOT/app" ]]; then
  say "Copying the new code to $ROOT/app"
  rsync -a --delete \
    --exclude 'db.sqlite3*' --exclude '.venv/' --exclude '__pycache__/' --exclude 'staticfiles/' --exclude '.env' \
    --exclude '.git/' \
    "$SRC/" "$ROOT/app/"
  chown -R root:"$APP_USER" "$ROOT/app"
  chmod -R u=rwX,g=rX,o= "$ROOT/app"
fi

say "Installing Python packages"
"$ROOT/venv/bin/pip" install --quiet -r "$ROOT/app/requirements.txt"
install -m 755 "$ROOT/app/deploy/manage.sh" "$ROOT/manage.sh"
install -m 755 "$ROOT/app/deploy/backup_db.sh" "$ROOT/backup_db.sh"
install -m 644 "$ROOT/app/deploy/tahoetable.service" /etc/systemd/system/tahoetable.service
systemctl daemon-reload

say "Updating the database and the static files"
as_app "$ROOT/manage.sh" migrate --noinput
as_app "$ROOT/manage.sh" collectstatic --noinput --clear --verbosity 0

say "Restarting the website"
systemctl restart tahoetable
sleep 2
if systemctl is-active --quiet tahoetable; then
  echo "The website is running the new version."
else
  echo "The website didn't start. See what went wrong with: journalctl -u tahoetable -n 50" >&2
  exit 1
fi
