"""Sending the site's email, and keeping a copy of each one.

Everything the site emails goes through send(): volunteer confirmations, notices to
organizers, donation receipts, password resets and test emails. Each one is saved, with
whether it went out, so admins can see the list on the Management page and send any of them
again. When no email service is connected, nothing is sent and the copy says so.
"""

import logging
import smtplib
import socket
import ssl
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.dispatch import Signal
from django.utils import timezone, translation

from .models import Email, EmailSettings

log = logging.getLogger("emails")

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
KEEP_DAYS = 183  # copies of emails are deleted after about six months
TIMEOUT = 10  # seconds to wait for the email service

# Sent after an email goes out, so the app it's about can note it: sender=Email, email=<Email>.
email_sent = Signal()


@dataclass
class Connection:
    """The email service the site sends through."""

    host: str
    port: int
    username: str
    password: str
    use_ssl: bool
    use_tls: bool
    source: str  # "site" when set on the Management page, "server" when set in /srv/tahoetable/.env


def current_connection(conf=None):
    """The email service to send through, or None when email is off.

    The Management page's settings come first. The EMAIL_HOST settings in the server's .env
    file are used when the Management page has none.
    """
    conf = conf or EmailSettings.load()
    if conf.host:
        use_ssl = conf.security == EmailSettings.SSL
        return Connection(
            host=conf.host, port=conf.port or (465 if use_ssl else 587), username=conf.username,
            password=conf.password, use_ssl=use_ssl, use_tls=not use_ssl, source="site",
        )
    if settings.EMAIL_HOST:
        return Connection(
            host=settings.EMAIL_HOST, port=settings.EMAIL_PORT, username=settings.EMAIL_HOST_USER,
            password=settings.EMAIL_HOST_PASSWORD, use_ssl=settings.EMAIL_USE_SSL,
            use_tls=settings.EMAIL_USE_TLS and not settings.EMAIL_USE_SSL, source="server",
        )
    return None


def is_on(conf=None):
    return current_connection(conf) is not None


def will_send(kind, conf=None):
    """Whether the site emails this kind of message: email is on, and the Management page didn't turn it off."""
    conf = conf or EmailSettings.load()
    if not is_on(conf):
        return False
    if kind == Email.VOLUNTEER:
        return conf.volunteer_confirmations
    if kind == Email.RECEIPT:
        return conf.donation_receipts
    if kind == Email.ORGANIZER:
        return bool(conf.notify_list)
    return True


def open_backend(connection):
    """A Django email backend for this connection.

    On the live site that's SMTP. Tests and local copies of the site can set EMAIL_BACKEND to
    keep emails in memory or print them instead.
    """
    if settings.EMAIL_BACKEND == SMTP_BACKEND:
        return get_connection(
            SMTP_BACKEND, fail_silently=False, host=connection.host, port=connection.port,
            username=connection.username, password=connection.password, use_ssl=connection.use_ssl,
            use_tls=connection.use_tls, timeout=TIMEOUT,
        )
    return get_connection(settings.EMAIL_BACKEND, fail_silently=False)


def check_login(conf):
    """Signs in to the email service without sending anything. Returns (problem, details), empty when it worked."""
    connection = current_connection(conf)
    if connection is None:
        return "", ""
    backend = open_backend(connection)
    try:
        backend.open()
    except Exception as exc:  # anything the email service or the network can raise
        return describe(exc)
    finally:
        try:
            backend.close()
        except Exception:
            pass
    return "", ""


def describe(exc):
    """What went wrong, as (problem, details): a code for Email.PROBLEMS, and the email service's own words."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        problem = "login"
    elif isinstance(exc, smtplib.SMTPSenderRefused):
        problem = "sender"
    elif isinstance(exc, smtplib.SMTPRecipientsRefused):
        problem = "recipient"
    elif isinstance(exc, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        problem = "tls"
    elif isinstance(exc, smtplib.SMTPResponseException):
        problem = "refused"
    elif isinstance(exc, (socket.timeout, TimeoutError)):
        problem = "timeout"
    elif isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError)):
        problem = "connect"
    else:
        problem = "other"

    if isinstance(exc, smtplib.SMTPResponseException):
        message = exc.smtp_error.decode("utf-8", "replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
        details = f"{exc.smtp_code} {message}"
    elif isinstance(exc, smtplib.SMTPRecipientsRefused):
        details = "; ".join(
            f"{address}: {code} {reply.decode('utf-8', 'replace') if isinstance(reply, bytes) else reply}"
            for address, (code, reply) in exc.recipients.items()
        )
    else:
        details = str(exc) or exc.__class__.__name__
    return problem, " ".join(details.split())[:500]


def _deliver(record, conf):
    """Tries to send one saved email. Updates its status but doesn't save it."""
    connection = current_connection(conf)
    if connection is None:
        record.status = Email.OFF
        return
    record.attempts += 1
    message = EmailMessage(
        subject=record.subject, body=record.body, from_email=conf.sender, to=record.recipients,
        reply_to=[record.reply_to] if record.reply_to else None, connection=open_backend(connection),
    )
    try:
        message.send()
    except Exception as exc:  # the email service or the network; the copy records what happened
        record.status = Email.FAILED
        record.problem, record.error = describe(exc)
        log.warning("Email %r to %s didn't go out: %s", record.subject, record.to, record.error)
    else:
        record.status = Email.SENT
        record.problem = record.error = ""
        record.sent_at = timezone.now()


def send(kind, to, subject, body, *, ref="", keep_body=True, conf=None):
    """Sends an email now, if email is on, and keeps a copy. Returns the copy (an Email).

    `to` is one address or a list of them. With keep_body=False the message itself isn't kept.
    It never is for password resets, so their links stay out of the database.
    """
    conf = conf or EmailSettings.load()
    to = [to] if isinstance(to, str) else [address for address in to if address]
    record = Email(
        kind=kind, to=", ".join(to), subject=" ".join(str(subject).split())[:300], body=body,
        reply_to=conf.reply_to or "", language=translation.get_language() or "", ref=ref,
    )
    _deliver(record, conf)
    if not keep_body or kind == Email.PASSWORD:
        record.body = ""
    record.save()
    Email.objects.filter(created_at__lt=timezone.now() - timedelta(days=KEEP_DAYS)).delete()
    if record.status == Email.SENT:
        email_sent.send(sender=Email, email=record)
    return record


def send_again(record):
    """Sends a kept email again, to the same people. Returns True when it went out."""
    if not record.can_send_again:
        return False
    conf = EmailSettings.load()
    record.reply_to = conf.reply_to or ""
    _deliver(record, conf)
    record.save()
    if record.status == Email.SENT:
        email_sent.send(sender=Email, email=record)
    return record.status == Email.SENT
