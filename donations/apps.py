from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DonationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "donations"
    verbose_name = _("Donations")

    def ready(self):
        from emails.sending import email_sent

        from .services import note_receipt_sent

        email_sent.connect(note_receipt_sent, dispatch_uid="donations.note_receipt_sent")
