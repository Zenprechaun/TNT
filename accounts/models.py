"""Roles and profiles. Every account has one profile, and a profile can have several roles."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Role(models.Model):
    """A named role such as Admin or User. Both are created by migration 0002."""

    ADMIN = "admin"
    USER = "user"
    BUILT_IN = (ADMIN, USER)

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(
        max_length=60, unique=True, help_text=_("Short name used in the code, such as admin or user.")
    )
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        """The role's name in the visitor's language. Admin and User are translated; other roles show as named."""
        built_in = {self.ADMIN: ("Admin", _("Admin")), self.USER: ("User", _("User"))}
        original, translated = built_in.get(self.slug, (None, None))
        return translated if self.name == original else self.name

    @property
    def is_built_in(self):
        """Admin and User can't be deleted, and their short names can't change."""
        return self.slug in self.BUILT_IN


class Profile(models.Model):
    """Extra details for an account, including its roles."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    roles = models.ManyToManyField(Role, related_name="profiles", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return _("Profile for %(username)s") % {"username": self.user.get_username()}

    def has_role(self, slug):
        return self.roles.filter(slug=slug).exists()

    @property
    def is_admin(self):
        return self.has_role(Role.ADMIN)
