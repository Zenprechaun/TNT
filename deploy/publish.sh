#!/usr/bin/env bash
# Automatic publishing for the Tahoe Neighborhood Table website.
#
# systemd runs this every minute on the server (tahoetable-publish.timer). It checks the
# "live" branch of the website's GitHub repository. When the branch has a new commit, it
# puts that version live with deploy/update.sh: a database backup, the new code, Python
# packages, database changes, static files and a restart. Then it checks that the site
# answers with the new version. If it doesn't, it puts the previous version back.
#
# GitHub Actions moves the "live" branch only after the tests pass
# (.github/workflows/publish.yml). setup_publishing.sh installs this script as
# /usr/local/sbin/tahoetable-publish.
#
# Run it by hand as root:
#     tahoetable-publish            publish the live branch if it has a new commit
#     tahoetable-publish --retry    try a version again after it failed
# See what it did:  journalctl -u tahoetable-publish -n 100
set -euo pipefail

ROOT="${PUBLISH_ROOT:-/srv/tahoetable}"   # the variables let the scripts be tested elsewhere
CONF="${PUBLISH_CONF:-/etc/tahoetable}"
REPO="$ROOT/repo"
STATUS_FILE="$ROOT/data/publish-status.json"
BRANCH="live"
RETRY=no
if [[ ${1:-} == "--retry" ]]; then
  RETRY=yes
fi

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root." >&2
  exit 1
fi

# One publish at a time.
exec 9>"$CONF/publish.lock"
if ! flock -n 9; then
  echo "Another publish is already running."
  exit 0
fi

DOMAIN="$(cat "$CONF/domain")"
export GIT_SSH_COMMAND="ssh -i $CONF/deploy_key -o IdentitiesOnly=yes -o UserKnownHostsFile=$CONF/known_hosts -o StrictHostKeyChecking=yes -o BatchMode=yes -o ConnectTimeout=20"

say() { printf '\n==> %s\n' "$1"; }

# Records the result where /healthz can report it: state is running, ok or failed.
write_status() {
  python3 - "$STATUS_FILE" "$TARGET" "$1" "$2" "$3" <<'PY'
import datetime, json, os, sys
path, revision, state, step, message = sys.argv[1:6]
data = {
    "revision": revision,
    "state": state,
    "step": step,
    "message": message,
    "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
}
tmp = path + ".tmp"
with open(tmp, "w") as fh:
    json.dump(data, fh)
os.chmod(tmp, 0o644)
os.replace(tmp, path)
PY
}

# True when the last publish of this same commit failed, so it isn't retried every minute.
already_failed() {
  python3 - "$STATUS_FILE" "$TARGET" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except (OSError, ValueError):
    sys.exit(1)
sys.exit(0 if isinstance(data, dict) and data.get("revision") == sys.argv[2] and data.get("state") == "failed" else 1)
PY
}

fetch() {  # path on the live site, through this server's own web server
  curl -fsS --max-time 10 --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN$1"
}

# True once the home page loads and /healthz reports the given commit.
runs_revision() {
  local expected="$1" body _
  for _ in $(seq 1 20); do
    if fetch / >/dev/null 2>&1 && body="$(fetch /healthz 2>/dev/null)" &&
      python3 -c 'import json, sys; d = json.loads(sys.argv[1]); sys.exit(0 if d.get("status") == "ok" and d.get("revision") == sys.argv[2] else 1)' "$body" "$expected"; then
      return 0
    fi
    sleep 3
  done
  return 1
}

home_page_loads() {
  local _
  for _ in $(seq 1 20); do
    if fetch / >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

TARGET="$(git -C "$REPO" ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | cut -f1 || true)"
if [[ ! $TARGET =~ ^[0-9a-f]{40}$ ]]; then
  echo "Couldn't read the $BRANCH branch from GitHub. Trying again next time." >&2
  exit 0
fi

CURRENT="$(cat "$ROOT/app/REVISION" 2>/dev/null || echo none)"
if [[ $TARGET == "$CURRENT" ]]; then
  exit 0
fi
if [[ $RETRY == no ]] && already_failed; then
  exit 0
fi

say "Publishing $TARGET (the site is running $CURRENT)"
write_status running fetch "Getting the new version from GitHub."
git -C "$REPO" fetch --quiet origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
git -C "$REPO" checkout --quiet --force --detach "$TARGET"
git -C "$REPO" clean -fdxq
echo "$TARGET" >"$REPO/REVISION"

say "Keeping a copy of the version that's live now"
rsync -a --delete "$ROOT/app/" "$ROOT/app.previous/"

write_status running update "Putting the new version live."
if bash "$REPO/deploy/update.sh" && runs_revision "$TARGET"; then
  write_status ok "done" "The website is running this version."
  say "Published $TARGET"
  exit 0
fi

echo "The new version didn't come up properly. Putting the previous version back." >&2
write_status running rollback "The new version didn't work. Putting the previous version back."
rsync -a --delete "$ROOT/app.previous/" "$ROOT/app/"
if bash "$ROOT/app/deploy/update.sh" && home_page_loads; then
  write_status failed update "The new version didn't work, so the previous version is live again. See: journalctl -u tahoetable-publish"
else
  write_status failed rollback "The new version didn't work, and putting the previous version back also failed. See: journalctl -u tahoetable-publish"
fi
exit 1
