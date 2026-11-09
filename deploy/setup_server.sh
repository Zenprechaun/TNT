#!/usr/bin/env bash
# First-time setup of the Tahoe Neighborhood Table website on a Hostinger VPS running Ubuntu 24.04.
#
# Upload and unzip the project on the server, then run this as root:
#     bash tahoe-neighborhood-table/deploy/setup_server.sh
#
# For a different domain:
#     DOMAIN=example.org bash tahoe-neighborhood-table/deploy/setup_server.sh
#
# It's safe to run again. It keeps the existing database and settings file.
set -euo pipefail

DOMAIN="${DOMAIN:-tahoeneighborhoodtable.com}"
APP_USER="tahoetable"
ROOT="/srv/tahoetable"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n==> %s\n' "$1"; }
as_app() { sudo -u "$APP_USER" "$@"; }

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root, for example: sudo bash $0" >&2
  exit 1
fi
if [[ ! -f "$SRC/manage.py" ]]; then
  echo "Couldn't find manage.py next to the deploy folder. Run this script from the unzipped project." >&2
  exit 1
fi

echo "Setting up the website for $DOMAIN and www.$DOMAIN."
CERT_EMAIL="${CERT_EMAIL:-}"
if [[ -z "$CERT_EMAIL" && -t 0 ]]; then
  read -rp "Email address for notices about the HTTPS certificate (or press Enter to skip): " CERT_EMAIL || CERT_EMAIL=""
fi

# A new server often runs Ubuntu's automatic updates for a while after it starts.
# Wait for them instead of failing.
apt_retry() {
  local n
  for n in $(seq 1 60); do
    if "$@"; then return 0; fi
    echo "Ubuntu's package manager is busy or didn't respond. Trying again in 10 seconds ($n of 60)." >&2
    sleep 10
  done
  return 1
}

say "Installing system packages"
apt_retry apt-get -o DPkg::Lock::Timeout=120 update -q
apt_retry env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a \
  apt-get -o DPkg::Lock::Timeout=120 install -y -q \
  python3 python3-venv nginx certbot python3-certbot-nginx ufw rsync curl sudo unzip

say "Creating the $APP_USER account and the folders in $ROOT"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$ROOT" --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -o root -g "$APP_USER" -m 750 "$ROOT"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$ROOT/data" "$ROOT/static" "$ROOT/backups"

say "Copying the website code to $ROOT/app"
rsync -a --delete \
  --exclude 'db.sqlite3*' --exclude '.venv/' --exclude '__pycache__/' --exclude 'staticfiles/' --exclude '.env' \
  --exclude '.git/' \
  "$SRC/" "$ROOT/app/"
chown -R root:"$APP_USER" "$ROOT/app"
chmod -R u=rwX,g=rX,o= "$ROOT/app"

say "Setting up the database"
if [[ -f "$ROOT/data/db.sqlite3" ]]; then
  echo "Keeping the existing database."
elif [[ -f "$SRC/db.sqlite3" ]]; then
  cp "$SRC/db.sqlite3" "$ROOT/data/db.sqlite3"
  echo "Copied the included database, which holds the Admin account."
fi
if [[ -f "$ROOT/data/db.sqlite3" ]]; then
  chown "$APP_USER:$APP_USER" "$ROOT/data/db.sqlite3"
fi

say "Creating the settings file $ROOT/.env"
if [[ -f "$ROOT/.env" ]]; then
  echo "Keeping the existing settings file."
else
  SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
  cat > "$ROOT/.env" <<EOF
# Settings for the live website. Keep this file private: it holds the secret key.
# See $ROOT/app/deploy/env.example for what each line does.
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=$SECRET_KEY
DJANGO_ALLOWED_HOSTS=$DOMAIN,www.$DOMAIN
DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN,https://www.$DOMAIN
DJANGO_DB_PATH=$ROOT/data/db.sqlite3
DJANGO_STATIC_ROOT=$ROOT/static
DJANGO_HSTS_SECONDS=0
EOF
fi
chown root:"$APP_USER" "$ROOT/.env"
chmod 640 "$ROOT/.env"

say "Installing Python packages"
if [[ ! -x "$ROOT/venv/bin/python" ]]; then
  python3 -m venv "$ROOT/venv"
fi
"$ROOT/venv/bin/pip" install --quiet --upgrade pip
"$ROOT/venv/bin/pip" install --quiet -r "$ROOT/app/requirements.txt"
install -m 755 "$ROOT/app/deploy/manage.sh" "$ROOT/manage.sh"
install -m 755 "$ROOT/app/deploy/backup_db.sh" "$ROOT/backup_db.sh"

say "Preparing the database and the static files"
as_app "$ROOT/manage.sh" migrate --noinput
as_app "$ROOT/manage.sh" collectstatic --noinput --clear --verbosity 0

say "Starting the app server (Gunicorn)"
install -m 644 "$ROOT/app/deploy/tahoetable.service" /etc/systemd/system/tahoetable.service
systemctl daemon-reload
systemctl enable tahoetable >/dev/null 2>&1
systemctl restart tahoetable

say "Setting up the web server (Nginx)"
sed "s/__DOMAIN__/$DOMAIN/g" "$ROOT/app/deploy/nginx.conf" > /etc/nginx/sites-available/tahoetable
ln -sf /etc/nginx/sites-available/tahoetable /etc/nginx/sites-enabled/tahoetable
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx >/dev/null 2>&1
systemctl reload-or-restart nginx

say "Turning on the firewall (SSH, http and https only)"
SSH_PORT="$(sshd -T 2>/dev/null | awk '$1 == "port" {print $2; exit}' || true)"
ufw allow "${SSH_PORT:-22}/tcp" >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null
echo "Open ports: ${SSH_PORT:-22} (SSH), 80 (http) and 443 (https)."

say "Scheduling a nightly database backup"
cat > /etc/cron.d/tahoetable-backup <<EOF
# Nightly copy of the website database, kept for 14 days in $ROOT/backups.
30 3 * * * $APP_USER $ROOT/backup_db.sh >/dev/null
EOF
chmod 644 /etc/cron.d/tahoetable-backup

say "Getting a free HTTPS certificate from Let's Encrypt"
CERT_ARGS=(--nginx --non-interactive --agree-tos --keep-until-expiring --redirect)
if [[ -n "$CERT_EMAIL" ]]; then
  CERT_ARGS+=(-m "$CERT_EMAIL")
else
  CERT_ARGS+=(--register-unsafely-without-email)
fi
CERT_OK=no
if certbot "${CERT_ARGS[@]}" -d "$DOMAIN" -d "www.$DOMAIN"; then
  CERT_OK=yes
elif certbot "${CERT_ARGS[@]}" -d "$DOMAIN"; then
  CERT_OK=yes
  echo "The certificate covers $DOMAIN only. Once www.$DOMAIN also points to this server, run:"
  echo "    certbot --nginx --expand -d $DOMAIN -d www.$DOMAIN"
fi

say "Checking the website"
if [[ $CERT_OK == yes ]]; then
  STATUS="$(curl -s -o /dev/null -w '%{http_code}' --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/" || true)"
else
  STATUS="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $DOMAIN" http://127.0.0.1/ || true)"
fi
if [[ $STATUS == 200 ]]; then
  echo "The home page loads."
else
  echo "The home page answered with status ${STATUS:-none}. See: journalctl -u tahoetable -n 50" >&2
fi

say "Choosing a new password for the Admin account"
if as_app "$ROOT/manage.sh" shell --verbosity 0 --command \
  "import sys; from django.contrib.auth import get_user_model; sys.exit(0 if get_user_model().objects.filter(username='Admin').exists() else 1)"; then
  if [[ -t 0 ]]; then
    as_app "$ROOT/manage.sh" changepassword Admin || echo "Password not changed. To change it later, run: sudo -u $APP_USER $ROOT/manage.sh changepassword Admin"
  else
    echo "To change it, run: sudo -u $APP_USER $ROOT/manage.sh changepassword Admin"
  fi
else
  echo "There's no Admin account. Create the first admin with: sudo -u $APP_USER $ROOT/manage.sh createsuperuser"
fi

echo
if [[ $CERT_OK == yes ]]; then
  echo "All set. The website is live at https://$DOMAIN"
else
  echo "The website is running, but it doesn't have an HTTPS certificate yet, and signing in needs HTTPS."
  echo "This usually means $DOMAIN doesn't point to this server yet. Once it does, run:"
  echo "    certbot --nginx --redirect -d $DOMAIN -d www.$DOMAIN"
fi
