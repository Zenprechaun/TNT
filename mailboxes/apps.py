from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class MailboxesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mailboxes"
    verbose_name = _("Staff and volunteer email")
