"""The Email section of the Management page: its forms, and what it shows."""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from . import dns
from .forms import EmailChoicesForm, EmailServiceForm, TestEmailForm
from .models import Email, EmailSettings
from .sending import KEEP_DAYS, check_login, current_connection, send, send_again

RECENT = 20


def _done(request, anchor, level, text):
    """Back to the Management page, with a note shown at the top of the Email section."""
    messages.add_message(request, level, text, extra_tags="email")
    return redirect(f"{reverse('accounts:manage')}#{anchor}")


def build_forms(request, conf, data=None, action=None):
    return {
        "service_form": EmailServiceForm(data if action == "connect" else None, conf=conf),
        "choices_form": EmailChoicesForm(data if action == "choices" else None, instance=conf),
        "test_form": TestEmailForm(data if action == "test" else None, initial={"to": request.user.email}),
    }


def handle(request):
    """Handles a form sent from the Email section.

    Returns a redirect once it's done, or the forms with their mistakes to show again.
    """
    conf = EmailSettings.load()
    action = request.POST.get("action", "")
    forms = build_forms(request, conf, request.POST, action)

    if action == "connect":
        form = forms["service_form"]
        if form.is_valid():
            form.save(request.user)
            problem, details = check_login(conf)
            if problem:
                return _done(request, "email-service", messages.ERROR, " ".join([
                    _("Saved, but the site couldn’t sign in to the email service."),
                    str(Email.PROBLEMS[problem]), _("Its answer: %(details)s") % {"details": details}]))
            conf.connected_at = timezone.now()
            conf.save(update_fields=["connected_at"])
            dns.forget(conf.from_address.split("@")[-1], conf.service)
            return _done(request, "email-test", messages.SUCCESS, _(
                "Email is on. The site signed in to %(service)s. Send yourself a test email to make sure it "
                "arrives.") % {"service": conf.service_name})

    elif action == "choices":
        form = forms["choices_form"]
        if form.is_valid():
            form.save()
            return _done(request, "email-choices", messages.SUCCESS, _("Saved which emails the site sends."))

    elif action == "test":
        form = forms["test_form"]
        if current_connection(conf) is None:
            return _done(request, "email-service", messages.ERROR, _("Connect an email service first."))
        if form.is_valid():
            address = form.cleaned_data["to"]
            body = render_to_string("emails/email/test.txt", {"sender": request.user, "service": conf.service_name})
            record = send(Email.TEST, address, _("Test email from Tahoe Neighborhood Table"), body, ref="test", conf=conf)
            if record.status == Email.SENT:
                return _done(request, "email-test", messages.SUCCESS, _(
                    "Sent a test email to %(address)s. If it isn’t there in a few minutes, look in the spam "
                    "folder.") % {"address": address})
            return _done(request, "email-log", messages.ERROR, " ".join([
                _("The test email didn’t go out."), str(record.problem_text),
                _("Its answer: %(details)s") % {"details": record.error}]))

    elif action == "send-again":
        pk = request.POST.get("email", "")
        if not pk.isdigit():
            raise Http404
        record = get_object_or_404(Email, pk=int(pk))
        if not record.can_send_again:
            return _done(request, "email-log", messages.ERROR, _("This email can’t be sent again."))
        if current_connection(conf) is None:
            return _done(request, "email-service", messages.ERROR, _("Connect an email service first."))
        if send_again(record):
            return _done(request, "email-log", messages.SUCCESS, _("Sent “%(subject)s” again to %(to)s.") % {
                "subject": record.subject, "to": record.to})
        return _done(request, "email-log", messages.ERROR, " ".join([
            _("It didn’t go out again."), str(record.problem_text),
            _("Its answer: %(details)s") % {"details": record.error}]))

    elif action == "disconnect":
        conf.service = conf.host = conf.username = conf.password_encrypted = conf.password_end = ""
        conf.port = None
        conf.connected_at = None
        conf.save()
        if current_connection(conf) is None:
            text = _("Email is off. The site won’t send email until you connect an email service again.")
        else:
            text = _("Removed. The site now uses the email settings in the server’s settings file.")
        return _done(request, "email-service", messages.SUCCESS, text)

    elif action == "check-dns":
        dns.forget(conf.from_address.split("@")[-1], conf.service)
        return redirect(f"{reverse('accounts:manage')}#email-dns")

    return forms


def section(request, forms=None):
    """What the Email section shows."""
    conf = EmailSettings.load()
    connection = current_connection(conf)
    domain = conf.from_address.split("@")[-1] if conf.from_address else ""
    recent = list(Email.objects.all()[:RECENT])
    context = {
        "conf": conf,
        "connection": connection,
        "on": connection is not None,
        "recent": recent,
        "dns_rows": dns.check(domain, conf.service if conf.host else "") if domain else [],
        "domain": domain,
        "keep_days": KEEP_DAYS,
        "presets": EmailSettings.PRESETS,
    }
    context.update(forms or build_forms(request, conf))
    return context


def status():
    """The Email tile at the top of the Management page: (state, chip, text)."""
    conf = EmailSettings.load()
    connection = current_connection(conf)
    if connection is None:
        return "off", _("Off"), _("Connect an email service so the site can send receipts, shift confirmations and "
                                  "password resets.")
    latest = Email.objects.exclude(status=Email.OFF).first()
    if latest and latest.status == Email.FAILED:
        return "warn", _("Problem"), _("The last email didn’t go out. See Recent emails.")
    name = conf.service_name if connection.source == "site" else connection.host
    return "ok", _("On"), _("Sending through %(service)s.") % {"service": name}
