"""The site's email: how it reaches the email service, and a copy of each email it sends."""

import re
from email.utils import formataddr

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .secrets import decrypt, encrypt


def default_site_email():
    return settings.SITE_EMAIL


def default_notify():
    return "\n".join(settings.VOLUNTEER_NOTIFY_EMAILS)


def split_addresses(text):
    """Addresses typed one per line, or separated by commas or semicolons."""
    return [part.strip() for part in re.split(r"[\n,;]+", text or "") if part.strip()]


class EmailSettings(models.Model):
    """How the site sends email, chosen on the Management page. There's only ever one row."""

    RESEND = "resend"
    BREVO = "brevo"
    GOOGLE = "google"
    OTHER = "other"
    SERVICES = [
        (RESEND, "Resend"),
        (BREVO, "Brevo"),
        (GOOGLE, _("Google Workspace or Gmail")),
        (OTHER, _("Another email service")),
    ]
    # What each service's SMTP settings are, filled in when it's chosen.
    PRESETS = {
        RESEND: {"host": "smtp.resend.com", "port": 465, "security": "ssl", "username": "resend"},
        BREVO: {"host": "smtp-relay.brevo.com", "port": 587, "security": "starttls"},
        GOOGLE: {"host": "smtp.gmail.com", "port": 465, "security": "ssl"},
    }

    SSL = "ssl"
    STARTTLS = "starttls"
    SECURITY = [(SSL, _("SSL/TLS, usually port 465")), (STARTTLS, _("STARTTLS, usually port 587"))]

    service = models.CharField(_("email service"), max_length=20, choices=SERVICES, blank=True)
    host = models.CharField(_("SMTP server"), max_length=255, blank=True)
    port = models.PositiveIntegerField(_("port"), null=True, blank=True)
    security = models.CharField(_("security"), max_length=10, choices=SECURITY, default=SSL)
    username = models.CharField(_("username"), max_length=255, blank=True)
    password_encrypted = models.TextField(blank=True)
    password_end = models.CharField(max_length=4, blank=True)  # the last characters, to tell keys apart
    from_name = models.CharField(_("sender name"), max_length=100, default="Tahoe Neighborhood Table")
    from_address = models.EmailField(_("send from"), default=default_site_email)
    reply_to = models.EmailField(_("replies go to"), blank=True, default=default_site_email)

    volunteer_confirmations = models.BooleanField(_("Email volunteers a copy of their shifts"), default=True)
    volunteer_notify = models.TextField(
        _("Tell these people about each new volunteer sign-up"), blank=True, default=default_notify,
        help_text=_("One email address per line. Leave it empty for nobody."),
    )
    donation_receipts = models.BooleanField(_("Email donors their receipt"), default=True)

    connected_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")

    class Meta:
        verbose_name = _("email settings")
        verbose_name_plural = _("email settings")

    def __str__(self):
        return str(_("Email settings"))

    @classmethod
    def load(cls):
        settings_row, _created = cls.objects.get_or_create(pk=1)
        return settings_row

    @property
    def password(self):
        return decrypt(self.password_encrypted)

    def set_password(self, raw):
        self.password_encrypted = encrypt(raw)
        self.password_end = raw[-4:] if len(raw) >= 12 else ""

    @property
    def password_unreadable(self):
        """True when a password is saved but this server's secret key can't read it."""
        return bool(self.password_encrypted) and not self.password

    @property
    def sender(self):
        return formataddr((self.from_name, self.from_address)) if self.from_address else settings.DEFAULT_FROM_EMAIL

    @property
    def notify_list(self):
        return split_addresses(self.volunteer_notify)

    @property
    def service_name(self):
        if self.service and self.service != self.OTHER:
            return self.get_service_display()
        return self.host


class Email(models.Model):
    """One email from the site, kept so admins can see what went out and send it again."""

    VOLUNTEER = "volunteer"
    ORGANIZER = "organizer"
    RECEIPT = "receipt"
    PASSWORD = "password"
    TEST = "test"
    KINDS = [
        (VOLUNTEER, _("Volunteer’s shifts")),
        (ORGANIZER, _("New volunteer notice")),
        (RECEIPT, _("Donation receipt")),
        (PASSWORD, _("Password reset")),
        (TEST, _("Test email")),
    ]

    SENT = "sent"
    FAILED = "failed"
    OFF = "off"
    STATUSES = [(SENT, _("Sent")), (FAILED, _("Didn’t go out")), (OFF, _("Not sent: email was off"))]

    # Why an email didn't go out. The details from the email service are in `error`.
    PROBLEMS = {
        "login": _("The email service didn’t accept the username and password (or API key)."),
        "sender": _("The email service won’t send from this address. Check that the domain is verified there."),
        "recipient": _("The email service turned down this address."),
        "refused": _("The email service turned down this email."),
        "connect": _("The site couldn’t reach the email service. Check the SMTP server and port."),
        "timeout": _("The email service didn’t answer in time."),
        "tls": _("The secure connection didn’t work. Check the security setting and the port."),
        "other": _("Something went wrong while sending."),
    }

    kind = models.CharField(_("email"), max_length=20, choices=KINDS)
    to = models.CharField(_("to"), max_length=1000)
    subject = models.CharField(_("subject"), max_length=300)
    body = models.TextField(_("message"), blank=True)
    reply_to = models.CharField(max_length=254, blank=True)
    language = models.CharField(_("language"), max_length=8, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES)
    problem = models.CharField(max_length=20, blank=True)
    error = models.TextField(_("details"), blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    ref = models.CharField(max_length=60, blank=True, help_text="What the email is about, like donation:42.")
    created_at = models.DateTimeField(_("created"), auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(_("sent"), null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = _("email")
        verbose_name_plural = _("emails")

    def __str__(self):
        return self.subject

    @property
    def recipients(self):
        return split_addresses(self.to)

    @property
    def problem_text(self):
        return self.PROBLEMS.get(self.problem, self.PROBLEMS["other"]) if self.status == self.FAILED else ""

    @property
    def can_send_again(self):
        """Password reset links aren't kept, so those can't be sent again."""
        return self.kind != self.PASSWORD and bool(self.body)
