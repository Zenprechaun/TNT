#!/usr/bin/env bash
# Runs Django management commands with the live website's settings.
# Run it as the website's account, for example:
#     sudo -u tahoetable /srv/tahoetable/manage.sh changepassword Admin
#     sudo -u tahoetable /srv/tahoetable/manage.sh createsuperuser
set -euo pipefail

ROOT="/srv/tahoetable"
set -a
# shellcheck source=/dev/null
. "$ROOT/.env"
set +a
export PYTHONDONTWRITEBYTECODE=1
cd "$ROOT/app"
exec "$ROOT/venv/bin/python" manage.py "$@"
