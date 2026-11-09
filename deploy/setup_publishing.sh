#!/usr/bin/env bash
# Turns on automatic publishing from GitHub on the server.
#
# deploy/bootstrap_publishing.sh runs this after it has created the server's deploy key
# and cloned the GitHub repository to /srv/tahoetable/repo. Running it again is safe, and
# it's also how to install a changed deploy/publish.sh or its timer:
#     bash /srv/tahoetable/repo/deploy/setup_publishing.sh
#
# For a different domain:
#     DOMAIN=example.org bash /srv/tahoetable/repo/deploy/setup_publishing.sh
set -euo pipefail

DOMAIN="${DOMAIN:-tahoeneighborhoodtable.com}"
ROOT="/srv/tahoetable"
REPO="$ROOT/repo"
CONF="/etc/tahoetable"

say() { printf '\n==> %s\n' "$1"; }

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root." >&2
  exit 1
fi
if [[ ! -d $ROOT/app || ! -f $ROOT/.env ]]; then
  echo "The website isn't set up on this server yet. Run deploy/setup_server.sh first." >&2
  exit 1
fi
if [[ ! -d $REPO/.git || ! -f $CONF/deploy_key || ! -f $CONF/known_hosts ]]; then
  echo "Couldn't find the repository in $REPO or the deploy key in $CONF." >&2
  echo "Run deploy/bootstrap_publishing.sh first." >&2
  exit 1
fi

say "Installing the publishing script and its timer"
echo "$DOMAIN" >"$CONF/domain"
install -m 755 "$REPO/deploy/publish.sh" /usr/local/sbin/tahoetable-publish
install -m 644 "$REPO/deploy/tahoetable-publish.service" /etc/systemd/system/tahoetable-publish.service
install -m 644 "$REPO/deploy/tahoetable-publish.timer" /etc/systemd/system/tahoetable-publish.timer
systemctl daemon-reload

say "Publishing the newest version on GitHub's live branch"
if ! /usr/local/sbin/tahoetable-publish --retry; then
  echo "That version didn't publish. The next version on GitHub will be tried automatically." >&2
fi
echo "The website is running: $(cat "$ROOT/app/REVISION" 2>/dev/null || echo "the version from before automatic publishing")"

say "Checking GitHub for new versions every minute"
systemctl enable --now tahoetable-publish.timer >/dev/null 2>&1
if systemctl is-active --quiet tahoetable-publish.timer; then
  echo "Automatic publishing is on."
else
  echo "The timer didn't start. See: systemctl status tahoetable-publish.timer" >&2
  exit 1
fi
cat <<EOF

See what it did:   journalctl -u tahoetable-publish -n 100
Pause it:          systemctl disable --now tahoetable-publish.timer
Turn it back on:   systemctl enable --now tahoetable-publish.timer
EOF
