"""Publishing and backups, for the Management page."""

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from .views import publish_status


def publishing():
    """The version that's running and how the latest automatic publish went."""
    status = publish_status() or {}
    finished = None
    if status.get("finished_at"):
        try:
            finished = datetime.fromisoformat(status["finished_at"])
        except (TypeError, ValueError):
            finished = None
    revision = settings.SITE_REVISION
    return {
        "revision": revision,
        "short": revision[:7] if revision != "development" else revision,
        "is_commit": revision != "development",
        "commit_url": f"{settings.GITHUB_REPOSITORY_URL}/commit/{revision}",
        "history_url": f"{settings.GITHUB_REPOSITORY_URL}/actions",
        "state": status.get("state") or "",
        "step": status.get("step") or "",
        "message": status.get("message") or "",
        "finished_at": finished,
        "failed_revision": (status.get("revision") or "")[:7] if status.get("state") == "failed" else "",
    }


def backups():
    """The nightly copies of the database in /srv/tahoetable/backups, or None where there's no such folder."""
    folder = settings.BACKUP_DIR
    try:
        files = [f for f in folder.glob("db-*.sqlite3") if f.is_file()] if folder.is_dir() else None
    except OSError:
        files = None
    if files is None:
        return None
    if not files:
        return {"count": 0, "latest": None, "size": 0, "stale": True, "folder": str(folder)}
    newest = max(files, key=lambda f: f.stat().st_mtime)
    stat = newest.stat()
    latest = datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone())
    return {
        "count": len(files),
        "latest": latest,
        "size": stat.st_size,
        # Backups run every night, so one older than a day and a half means they've stopped.
        "stale": timezone.now() - latest > timedelta(hours=36),
        "folder": str(folder),
    }
