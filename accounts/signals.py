"""Keep every account's profile, and its access to the admin site, in step with its roles."""

from django.contrib.auth import get_user_model
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from .models import Profile, Role
from .roles import default_roles_for

User = get_user_model()


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, raw=False, **kwargs):
    """Give every new account a profile with the default roles."""
    if raw:  # loading fixtures
        return
    profile, made = Profile.objects.get_or_create(user=instance)
    if made:
        profile.roles.add(*default_roles_for(instance))


def sync_admin_access(profile):
    """The Admin role is what grants Django's staff and superuser status, which open the admin site."""
    is_admin = profile.roles.filter(slug=Role.ADMIN).exists()
    User.objects.filter(pk=profile.user_id).exclude(is_staff=is_admin, is_superuser=is_admin).update(
        is_staff=is_admin, is_superuser=is_admin
    )


@receiver(m2m_changed, sender=Profile.roles.through)
def roles_changed(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    if not reverse:  # roles were changed on one profile
        sync_admin_access(instance)
        return
    # People were added to or removed from a role.
    profiles = Profile.objects.filter(pk__in=pk_set) if pk_set else Profile.objects.all()
    for profile in profiles:
        sync_admin_access(profile)
