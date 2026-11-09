#!/usr/bin/env bash
# First step of automatic publishing. Run it once as root on the server:
#     bash bootstrap_publishing.sh git@github.com:OWNER/REPO.git
#
# It creates the server's deploy key, which can only read the repository, and waits until
# the key is added on GitHub (Settings > Deploy keys). Then it clones the repository to
# /srv/tahoetable/repo and runs deploy/setup_publishing.sh.
set -euo pipefail

REPO_URL="${1:?Give the repository, like git@github.com:OWNER/REPO.git}"
CONF="/etc/tahoetable"
REPO="/srv/tahoetable/repo"

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root." >&2
  exit 1
fi
if ! command -v git >/dev/null; then
  apt-get install -y -q git
fi

install -d -m 700 "$CONF"
if [[ ! -f $CONF/deploy_key ]]; then
  ssh-keygen -q -t ed25519 -N '' -C "tahoetable-server" -f "$CONF/deploy_key"
fi
# GitHub's published SSH host keys, fetched over HTTPS.
curl -fsS https://api.github.com/meta |
  python3 -c 'import json, sys; print("\n".join("github.com " + key for key in json.load(sys.stdin)["ssh_keys"]))' \
    >"$CONF/known_hosts"
export GIT_SSH_COMMAND="ssh -i $CONF/deploy_key -o IdentitiesOnly=yes -o UserKnownHostsFile=$CONF/known_hosts -o StrictHostKeyChecking=yes -o BatchMode=yes"

if ! git ls-remote "$REPO_URL" >/dev/null 2>&1; then
  echo
  echo "Add this key on GitHub: the repository's Settings > Deploy keys > Add deploy key."
  echo "Leave \"Allow write access\" unchecked."
  echo
  cat "$CONF/deploy_key.pub"
  echo
  printf 'Waiting for GitHub to accept the key'
  until git ls-remote "$REPO_URL" >/dev/null 2>&1; do
    printf '.'
    sleep 10
  done
  echo
fi
echo "GitHub accepted the key."

if [[ ! -d $REPO/.git ]]; then
  git clone --quiet --branch live "$REPO_URL" "$REPO"
fi
git -C "$REPO" remote set-url origin "$REPO_URL"
bash "$REPO/deploy/setup_publishing.sh"
