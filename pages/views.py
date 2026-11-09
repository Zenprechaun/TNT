import json

from django.conf import settings
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from volunteers.views import signup_context


def home(request):
    """The home page. It also carries the volunteer sign-up pop-up for the next open event."""
    return render(request, "pages/home.html", signup_context(request=request))


# The fields of the publish status that /healthz passes on. deploy/publish.sh writes them.
PUBLISH_FIELDS = ("revision", "state", "step", "message", "finished_at")


def publish_status():
    """The result of the latest automatic publish on the server, or None if there isn't one."""
    try:
        status = json.loads(settings.PUBLISH_STATUS_FILE.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(status, dict):
        return None
    return {field: status.get(field) for field in PUBLISH_FIELDS}


@require_GET
@never_cache
def healthz(request):
    """Shows whether the site and its database work, and which version of the code is running.

    Automatic publishing and GitHub Actions use this to confirm a new version is live.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database = "ok"
    except DatabaseError:
        database = "unavailable"
    healthy = database == "ok"
    return JsonResponse(
        {
            "status": "ok" if healthy else "error",
            "database": database,
            "revision": settings.SITE_REVISION,
            "publish": publish_status(),
        },
        status=200 if healthy else 503,
    )
