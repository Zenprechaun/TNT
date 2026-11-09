from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .roles import user_has_role


def role_required(*slugs):
    """Allow a view only for signed-in people who have at least one of these roles.

    Signed-out visitors are sent to the login page. Anyone else gets the 403 page.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not user_has_role(request.user, *slugs):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return login_required(_wrapped)

    return decorator
