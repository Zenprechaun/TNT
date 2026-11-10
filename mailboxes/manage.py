"""The Staff and volunteer email section of the Management page."""

import secrets

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from emails.secrets import decrypt, encrypt

from .forms import ChangeAccountForm, ConnectionForm, NewAccountForm, manager_choices
from .google import (Directory, GoogleError, authorization_url, new_pkce, redirect_uri, revoke,
                     temporary_password)
from .models import KINDS, AccountChange, GoogleConnection

ACTIONS = ("google-settings", "google-connect", "google-disconnect", "account-create", "account-suspend",
           "account-restore", "account-password", "account-change", "account-delete")
SESSION_PASSWORD = "mailboxes:new-password"
SESSION_SIGN_IN = "mailboxes:sign-in"
QUARANTINE_URL = "https://admin.google.com/ac/moderation"
ADMIN_CONSOLE_URL = "https://admin.google.com"
RECENT_CHANGES = 12


def done(request, level, text, anchor="mailboxes"):
    """Back to the Management page, with a note shown at the top of this section."""
    messages.add_message(request, level, text, extra_tags="mailboxes")
    return redirect(f"{reverse('accounts:manage')}#{anchor}")


def _record(request, action, address, kind="", manager=""):
    AccountChange.objects.create(action=action, address=address, kind=kind, manager=manager, by=request.user,
                                 by_name=request.user.get_full_name() or request.user.get_username())


def _show_password(request, email, password, action):
    """Keeps a new temporary password, encrypted, until the next page shows it once."""
    request.session[SESSION_PASSWORD] = {"email": email, "password": encrypt(password), "action": action}


def _active_staff(accounts):
    return [a for a in accounts if a.kind == "staff" and not a.suspended]


def handle(request):
    """Handles a form sent from this section. Returns a redirect when it's done, or forms with mistakes."""
    conn = GoogleConnection.load()
    action = request.POST.get("action", "")

    if action == "google-settings":
        form = ConnectionForm(request.POST, conn=conn)
        if form.is_valid():
            form.save(request.user)
            if conn.is_connected:
                return done(request, messages.SUCCESS, _("Saved."))
            return done(request, messages.SUCCESS, _(
                "Saved. Now choose Connect Google and sign in as the website’s admin account."))
        return {"connection_form": form}

    if action == "google-connect":
        if not conn.is_set_up:
            return done(request, messages.ERROR, _("Save the OAuth client ID and secret first."))
        state = secrets.token_urlsafe(24)
        verifier, challenge = new_pkce()
        request.session[SESSION_SIGN_IN] = {"state": state, "verifier": verifier}
        return redirect(authorization_url(conn, state, challenge))

    if action == "google-disconnect":
        revoke(conn)
        conn.refresh_token_encrypted = conn.connected_as = ""
        conn.connected_at = None
        conn.save()
        return done(request, messages.SUCCESS, _(
            "Disconnected. The email accounts keep working; the site just can’t change them until Google is "
            "connected again."))

    if not conn.is_connected:
        return done(request, messages.ERROR, _("Connect Google first."))

    directory = Directory(conn)
    email = request.POST.get("email", "").strip().lower()
    try:
        if action == "account-create":
            accounts = directory.accounts()
            form = NewAccountForm(request.POST, staff=_active_staff(accounts), domain=conn.domain)
            if not form.is_valid():
                return {"new_form": form, "accounts": accounts}
            data = form.cleaned_data
            password = temporary_password()
            account = directory.create(email=form.email, first_name=data["first_name"].strip(),
                                       last_name=data["last_name"].strip(), kind=data["kind"],
                                       manager=data["manager"], password=password)
            _record(request, AccountChange.CREATED, account.email, data["kind"], data["manager"])
            _show_password(request, account.email, password, "created")
            return done(request, messages.SUCCESS, _("Created %(email)s.") % {"email": account.email})

        if action == "account-suspend":
            directory.changeable(email)
            directory.update(email, suspended=True)
            _record(request, AccountChange.SUSPENDED, email)
            return done(request, messages.SUCCESS, _(
                "Suspended %(email)s. They can’t sign in until you restore the account.") % {"email": email})

        if action == "account-restore":
            directory.changeable(email)
            directory.update(email, suspended=False)
            _record(request, AccountChange.RESTORED, email)
            return done(request, messages.SUCCESS, _("Restored %(email)s. They can sign in again.") % {"email": email})

        if action == "account-password":
            directory.changeable(email)
            password = temporary_password()
            directory.update(email, password=password, changePasswordAtNextLogin=True)
            _record(request, AccountChange.PASSWORD, email)
            _show_password(request, email, password, "reset")
            return done(request, messages.SUCCESS, _("Reset the password for %(email)s.") % {"email": email})

        if action == "account-change":
            accounts = directory.accounts()
            form = ChangeAccountForm(request.POST, staff=_active_staff(accounts))
            if not form.is_valid():
                return done(request, messages.ERROR, _("Choose staff or volunteer, and a manager from the list."))
            directory.changeable(email)
            data = form.cleaned_data
            manager = data["manager"]
            directory.update(email, orgUnitPath=conn.unit_for(data["kind"]),
                             relations=[{"type": "manager", "value": manager}] if manager else None)
            _record(request, AccountChange.CHANGED, email, data["kind"], manager)
            return done(request, messages.SUCCESS, _("Saved the changes to %(email)s.") % {"email": email})

        if action == "account-delete":
            if request.POST.get("confirm", "").strip().lower() != email:
                return done(request, messages.ERROR, _(
                    "Not deleted. To delete %(email)s, type its address exactly.") % {"email": email})
            directory.changeable(email)
            directory.delete(email)
            _record(request, AccountChange.DELETED, email)
            return done(request, messages.SUCCESS, _(
                "Deleted %(email)s. For 20 days, a Google admin can still restore it in the Google Admin "
                "console.") % {"email": email})

    except GoogleError as exc:
        return done(request, messages.ERROR, _("Google said: %(reason)s") % {"reason": exc.message})

    return {}


def section(request, forms=None):
    """What the Staff and volunteer email section shows."""
    forms = forms or {}
    conn = GoogleConnection.load()
    context = {
        "conn": conn,
        "connected": conn.is_connected,
        "redirect_uri": redirect_uri(),
        "connection_form": forms.get("connection_form") or ConnectionForm(conn=conn),
        "changes": list(AccountChange.objects.select_related("by")[:RECENT_CHANGES]),
        "quarantine_url": QUARANTINE_URL,
        "admin_console_url": ADMIN_CONSOLE_URL,
        "accounts": forms.get("accounts"),
        "error": "",
        "reconnect": False,
    }
    if conn.is_connected and context["accounts"] is None:
        try:
            context["accounts"] = Directory(conn).accounts()
        except GoogleError as exc:
            context["error"], context["reconnect"] = exc.message, exc.reconnect
    accounts = context["accounts"] or []
    names = {a.email: a.name for a in accounts}
    for account in accounts:
        account.manager_name = names.get(account.manager, account.manager)
    staff = _active_staff(accounts)
    context["new_form"] = forms.get("new_form") or NewAccountForm(staff=staff, domain=conn.domain)
    context["manager_choices"] = manager_choices(staff)
    context["kinds"] = KINDS
    context["counts"] = {
        "total": len(accounts),
        "staff": sum(1 for a in accounts if a.kind == "staff"),
        "volunteers": sum(1 for a in accounts if a.kind == "volunteer"),
        "suspended": sum(1 for a in accounts if a.suspended),
    }
    shown = request.session.pop(SESSION_PASSWORD, None)
    if shown:
        context["new_password"] = {"email": shown["email"], "password": decrypt(shown["password"]),
                                   "action": shown["action"]}
    return context


def status(context):
    """The Staff email tile at the top of the Management page: (state, chip, text)."""
    if not context["connected"]:
        return "off", _("Not connected"), _(
            "Connect Google Workspace to create and manage staff and volunteer email accounts here.")
    if context["error"]:
        return "warn", _("Problem"), _("Google didn’t answer. See Staff and volunteer email.")
    counts = context["counts"]
    text = ngettext("%(count)s account.", "%(count)s accounts.", counts["total"]) % {"count": counts["total"]}
    if counts["suspended"]:
        text = " ".join([text, ngettext("%(count)s suspended.", "%(count)s suspended.", counts["suspended"]) % {
            "count": counts["suspended"]}])
    return "ok", _("Connected"), text
