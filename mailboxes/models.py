"""Staff and volunteer email accounts in Google Workspace, managed from the Management page.

The accounts themselves live in Google. The site keeps only how to reach Google (with the
secrets encrypted), and a record of each change an admin made from the Management page.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from emails.secrets import decrypt, encrypt

KINDS = [("staff", _("Staff")), ("volunteer", pgettext_lazy("person", "Volunteer"))]


def default_domain():
    return settings.SITE_EMAIL.split("@")[-1]


class GoogleConnection(models.Model):
    """How the site signs in to Google Workspace. There's only ever one row."""

    client_id = models.CharField(_("OAuth client ID"), max_length=255, blank=True)
    client_secret_encrypted = models.TextField(blank=True)
    refresh_token_encrypted = models.TextField(blank=True)
    connected_as = models.EmailField(_("signed in as"), blank=True)
    connected_at = models.DateTimeField(_("connected"), null=True, blank=True)
    domain = models.CharField(_("domain"), max_length=255, default=default_domain)
    staff_unit = models.CharField(_("staff organizational unit"), max_length=255, default="/Staff")
    volunteer_unit = models.CharField(_("volunteer organizational unit"), max_length=255, default="/Volunteers")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")

    class Meta:
        verbose_name = _("Google Workspace connection")
        verbose_name_plural = _("Google Workspace connection")

    def __str__(self):
        return self.connected_as or self.domain

    @classmethod
    def load(cls):
        connection, _created = cls.objects.get_or_create(pk=1)
        return connection

    @property
    def client_secret(self):
        return decrypt(self.client_secret_encrypted)

    def set_client_secret(self, raw):
        self.client_secret_encrypted = encrypt(raw)

    @property
    def refresh_token(self):
        return decrypt(self.refresh_token_encrypted)

    def set_refresh_token(self, raw):
        self.refresh_token_encrypted = encrypt(raw)

    @property
    def is_set_up(self):
        """The OAuth client is saved, so an admin can choose Connect Google."""
        return bool(self.client_id and self.client_secret)

    @property
    def is_connected(self):
        return self.is_set_up and bool(self.refresh_token)

    def unit_for(self, kind):
        return self.staff_unit if kind == "staff" else self.volunteer_unit


class AccountChange(models.Model):
    """One change an admin made to a staff or volunteer email account from the Management page."""

    CREATED = "created"
    SUSPENDED = "suspended"
    RESTORED = "restored"
    PASSWORD = "password"
    CHANGED = "changed"
    DELETED = "deleted"
    ACTIONS = [
        (CREATED, _("Created")),
        (SUSPENDED, _("Suspended")),
        (RESTORED, _("Restored")),
        (PASSWORD, _("Password reset")),
        (CHANGED, _("Changed")),
        (DELETED, _("Deleted")),
    ]

    action = models.CharField(_("action"), max_length=12, choices=ACTIONS)
    address = models.EmailField(_("account"))
    kind = models.CharField(_("staff or volunteer"), max_length=10, choices=KINDS, blank=True)
    manager = models.EmailField(_("manager"), blank=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                           related_name="+", verbose_name=_("by"))
    by_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(_("when"), auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = _("email account change")
        verbose_name_plural = _("email account changes")

    def __str__(self):
        return f"{self.get_action_display()}: {self.address}"
