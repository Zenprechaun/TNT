"""The Management page for admins: email, staff and volunteer email accounts, volunteer events, donations,
publishing and backups."""

from django.http import Http404
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404, render
from django.utils.timesince import timesince
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from donations import summary as donation_summary
from donations.admin import DONATION_HEADER, donation_rows
from donations.models import Donation, stripe_mode
from emails import manage as email_manage
from mailboxes import manage as mailbox_manage
from pages import status
from pages.spreadsheets import csv_download
from volunteers import summary as volunteer_summary
from volunteers.admin import ROSTER_HEADER, roster_rows
from volunteers.models import Assignment, Event

from .decorators import role_required
from .models import Role


def _ago(moment):
    """How long ago, roughly: 3 hours, or 2 days."""
    return timesince(moment, depth=1)


def _tile(key, label, state, chip, text, href):
    return {"key": key, "label": label, "state": state, "chip": chip, "text": text, "href": href}


def tiles(mailboxes, events, giving, publishing, backups):
    """The row of tiles at the top: each part of the site, and whether it needs attention."""
    state, chip, text = email_manage.status()
    rows = [_tile("email", _("Email"), state, chip, text, "#email")]
    state, chip, text = mailbox_manage.status(mailboxes)
    rows.append(_tile("mailboxes", _("Staff email"), state, chip, text, "#mailboxes"))

    if not giving["connected"]:
        rows.append(_tile("donations", _("Donations"), "off", _("Off"),
                          _("Stripe isn’t connected, so the Donate button opens an email."), "#donations"))
    else:
        if giving["livemode"]:
            state, chip = "ok", _("Live")
            text = _("Taking real donations: %(total)s so far in %(year)s.") % {
                "total": giving["total"], "year": giving["year"]}
        else:
            state, chip = "warn", _("Test mode")
            text = _("Test cards only, until the live key is added.")
        if not giving["updates_connected"]:
            state = "warn"
            text = " ".join([text, _("Payment updates from Stripe aren’t connected: run connect_stripe.")])
        rows.append(_tile("donations", _("Donations"), state, chip, text, "#donations"))

    if events:
        nxt = events[0]
        text = _("Next: %(event)s, %(dates)s. %(taken)s of %(total)s spots filled.") % {
            "event": nxt["event"], "dates": nxt["dates"], "taken": nxt["taken"], "total": nxt["total"]}
        if nxt["accepting"]:
            rows.append(_tile("volunteers", _("Volunteers"), "ok", _("Sign-ups open"), text, "#volunteers"))
        else:
            rows.append(_tile("volunteers", _("Volunteers"), "off", _("Sign-ups closed"), text, "#volunteers"))
    else:
        rows.append(_tile("volunteers", _("Volunteers"), "off", _("No events"),
                          _("No upcoming volunteer events."), "#volunteers"))

    if publishing["state"] == "failed":
        rows.append(_tile("publishing", _("Publishing"), "warn", _("Failed"),
                          _("The last update didn’t go live. The site kept the version before it."), "#site"))
    elif publishing["state"] == "running":
        rows.append(_tile("publishing", _("Publishing"), "ok", _("Updating"),
                          _("A new version is going live now."), "#site"))
    elif publishing["is_commit"]:
        text = _("Version %(version)s is live.") % {"version": publishing["short"]}
        if publishing["finished_at"]:
            text = _("Version %(version)s went live %(ago)s ago.") % {
                "version": publishing["short"], "ago": _ago(publishing["finished_at"])}
        rows.append(_tile("publishing", _("Publishing"), "ok", _("Up to date"), text, "#site"))
    else:
        rows.append(_tile("publishing", _("Publishing"), "off", _("Not published"),
                          _("This copy of the site isn’t published from GitHub."), "#site"))

    if backups is None:
        rows.append(_tile("backups", _("Backups"), "off", _("Not here"),
                          _("Backups run on the live server."), "#site"))
    elif not backups["count"]:
        rows.append(_tile("backups", _("Backups"), "warn", _("None yet"),
                          _("There are no backups of the database yet."), "#site"))
    else:
        kept = ngettext("%(count)s copy kept.", "%(count)s copies kept.", backups["count"]) % {
            "count": backups["count"]}
        if backups["stale"]:
            text = _("The newest backup is %(ago)s old, so nightly backups may have stopped.") % {
                "ago": _ago(backups["latest"])}
            rows.append(_tile("backups", _("Backups"), "warn", _("Check"), text, "#site"))
        else:
            text = " ".join([_("Last backup %(ago)s ago.") % {"ago": _ago(backups["latest"])}, kept])
            rows.append(_tile("backups", _("Backups"), "ok", _("OK"), text, "#site"))
    return rows


@require_http_methods(["GET", "POST"])
@never_cache
@role_required(Role.ADMIN)
def manage(request):
    email_forms = mailbox_forms = None
    if request.method == "POST":
        if request.POST.get("action") in mailbox_manage.ACTIONS:
            result = mailbox_forms = mailbox_manage.handle(request)
        else:
            result = email_forms = email_manage.handle(request)
        if isinstance(result, HttpResponseBase):
            return result  # done, or off to Google to sign in

    mailboxes = mailbox_manage.section(request, mailbox_forms)
    events = volunteer_summary.upcoming_events()
    giving = donation_summary.totals()
    publishing = status.publishing()
    backups = status.backups()
    return render(request, "accounts/manage.html", {
        "dash": "manage",
        "email": email_manage.section(request, email_forms),
        "mailboxes": mailboxes,
        "events": events,
        "signups": volunteer_summary.recent_signups(),
        "giving": giving,
        "donations": donation_summary.recent(),
        "publishing": publishing,
        "backups": backups,
        "tiles": tiles(mailboxes, events, giving, publishing, backups),
    })


@require_GET
@role_required(Role.ADMIN)
def roster_csv(request, pk):
    """The roster of one event, every shift, as a spreadsheet."""
    event = get_object_or_404(Event, pk=pk)
    assignments = (Assignment.objects.filter(shift__event=event, cancelled=False)
                   .select_related("signup", "shift__role", "shift__event")
                   .order_by("shift__date", "shift__start", "signup__last_name"))
    return csv_download(f"{event.slug}-roster.csv", ROSTER_HEADER, roster_rows(assignments))


@require_GET
@role_required(Role.ADMIN)
def donations_csv(request, year):
    """One year's donations, paid or refunded, as a spreadsheet."""
    if not 2000 <= year <= 2100:
        raise Http404
    donations = Donation.objects.filter(livemode=stripe_mode() == "live", paid_at__year=year,
                                        status__in=[Donation.PAID, Donation.REFUNDED]).order_by("paid_at", "pk")
    return csv_download(f"donations-{year}.csv", DONATION_HEADER, donation_rows(donations))
