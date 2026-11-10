from emails.sending import is_on as email_is_on

from .roles import is_admin


def account(request):
    """Lets every template know whether the signed-in person has the Admin role, and whether
    "Forgot your password?" can work (it needs email). That one is only looked up when a
    template asks."""
    user = getattr(request, "user", None)
    return {
        "is_admin_user": bool(user is not None and user.is_authenticated and is_admin(user)),
        "password_reset_on": email_is_on,
    }
