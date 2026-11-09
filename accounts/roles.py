"""Helpers for checking roles and choosing where people land after they sign in."""

from django.urls import reverse

from .models import Profile, Role


def default_roles_for(user):
    """Everyone starts with the User role. Superusers also get the Admin role."""
    slugs = [Role.USER, Role.ADMIN] if user.is_superuser else [Role.USER]
    return Role.objects.filter(slug__in=slugs)


def get_profile(user):
    """Return the account's profile, creating it with the default roles if it's missing."""
    profile, created = Profile.objects.get_or_create(user=user)
    if created:
        profile.roles.add(*default_roles_for(user))
    return profile


def user_has_role(user, *slugs):
    """True when a signed-in account has at least one of the given roles."""
    if not getattr(user, "is_authenticated", False):
        return False
    return Profile.objects.filter(user=user, roles__slug__in=slugs).exists()


def is_admin(user):
    return user_has_role(user, Role.ADMIN)


def dashboard_url_for(user):
    """Admins go to the Admin's Dashboard. Everyone else goes to the User's Dashboard."""
    return reverse("accounts:admin_dashboard" if is_admin(user) else "accounts:user_dashboard")
