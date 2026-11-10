"""Where Google sends the admin back after they sign in to connect Google Workspace."""

import secrets

from django.contrib import messages
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.decorators import role_required
from accounts.models import Role

from .google import SCOPES, GoogleError, exchange_code, forget_token, signed_in_as
from .manage import SESSION_SIGN_IN, done
from .models import GoogleConnection


@require_GET
@never_cache
@role_required(Role.ADMIN)
def callback(request):
    started = request.session.pop(SESSION_SIGN_IN, None)
    if request.GET.get("error"):
        return done(request, messages.ERROR, _("Google didn’t connect: %(reason)s") % {"reason": request.GET["error"]})
    if not started or not secrets.compare_digest(request.GET.get("state", ""), started["state"]):
        return done(request, messages.ERROR, _("That sign-in was out of date. Choose Connect Google again."))

    conn = GoogleConnection.load()
    try:
        answer = exchange_code(conn, request.GET.get("code", ""), started["verifier"])
    except GoogleError as exc:
        return done(request, messages.ERROR, exc.message)

    email, domain = signed_in_as(answer)
    if domain.lower() != conn.domain.lower():
        return done(request, messages.ERROR, _(
            "Sign in with the website’s admin account at %(domain)s, not %(email)s.") % {
            "domain": conn.domain, "email": email or _("another account")})
    if SCOPES[-1] not in answer.get("scope", "").split():
        return done(request, messages.ERROR, _(
            "Google didn’t give the site permission to manage user accounts. Choose Connect Google again and "
            "allow it."))
    if not answer.get("refresh_token"):
        return done(request, messages.ERROR, _(
            "Google didn’t give the site lasting access. Choose Connect Google again."))

    conn.set_refresh_token(answer["refresh_token"])
    conn.connected_as = email
    conn.connected_at = timezone.now()
    conn.updated_by = request.user
    conn.save()
    forget_token()
    return done(request, messages.SUCCESS, _("Connected to Google Workspace as %(email)s.") % {"email": email})
