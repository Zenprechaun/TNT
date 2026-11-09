from .roles import is_admin


def account(request):
    """Lets every template know whether the signed-in person has the Admin role."""
    user = getattr(request, "user", None)
    return {"is_admin_user": bool(user is not None and user.is_authenticated and is_admin(user))}
