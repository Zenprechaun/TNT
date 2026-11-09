"""A simple limit on how often one visitor can do something, like creating accounts."""

from django.core.cache import cache


def client_ip(request):
    # Nginx passes the visitor's address in X-Real-IP; it replaces any value a visitor sends.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "")


def over_limit(request, action, limit, seconds):
    """Counts this attempt, and returns True once the visitor has made more than `limit` within `seconds`."""
    key = f"limit:{action}:{client_ip(request)}"
    if cache.add(key, 1, seconds):
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:  # the count just expired
        cache.set(key, 1, seconds)
        return False
