"""Talking to Google Workspace: signing in with OAuth, and its Directory API for user accounts.

The site signs in as one Google admin account made for the website, with Google's prebuilt
User Management Admin role, which can't change administrators. Google gives the site a
refresh token for that account, which is stored encrypted. The site never reads anyone's
email: it only asks for the scope that manages user accounts.

Every request goes through http(), which the tests replace with a fake Google.
"""

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils.translation import gettext as _

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERS_URL = "https://admin.googleapis.com/admin/directory/v1/users"
SCOPES = ["openid", "email", "https://www.googleapis.com/auth/admin.directory.user"]
TIMEOUT = 15
TOKEN_CACHE_KEY = "mailboxes:google-access-token"
PASSWORD_LETTERS = "abcdefghjkmnpqrstuvwxyz23456789"  # no l, o, 0 or 1, which are easy to misread


class GoogleError(Exception):
    """Google said no, or couldn't be reached. `reconnect` is True when an admin has to connect Google again."""

    def __init__(self, message, status=None, reconnect=False):
        super().__init__(message)
        self.message = message
        self.status = status
        self.reconnect = reconnect


def http(method, url, *, form=None, body=None, token=None):
    """Makes one request to Google and returns (status, its JSON answer as a dict)."""
    headers = {"Accept": "application/json"}
    data = None
    if form is not None:
        data = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            status, raw = response.status, response.read()
    except HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (URLError, OSError) as exc:  # no network, a timeout, or a TLS problem
        raise GoogleError(_("The site couldn’t reach Google. Try again in a few minutes.")) from exc
    try:
        answer = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        answer = {}
    return status, answer if isinstance(answer, dict) else {}


def _reason(answer, status):
    """Google's own explanation, from either kind of error answer."""
    error = answer.get("error")
    if isinstance(error, dict) and error.get("message"):
        return error["message"]
    return answer.get("error_description") or (error if isinstance(error, str) else "") or f"HTTP {status}"


# ---------- signing in ----------

def redirect_uri():
    """Where Google sends the admin back to. It has to be listed exactly like this in the OAuth client."""
    return settings.SITE_URL.rstrip("/") + reverse("mailboxes:callback")


def new_pkce():
    """A one-time secret for this sign-in (PKCE), and the fingerprint of it that Google gets first."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorization_url(conn, state, challenge):
    params = {
        "client_id": conn.client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent select_account",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "hd": conn.domain,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(conn, code, verifier):
    status, answer = http("POST", TOKEN_URL, form={
        "code": code, "client_id": conn.client_id, "client_secret": conn.client_secret,
        "redirect_uri": redirect_uri(), "grant_type": "authorization_code", "code_verifier": verifier,
    })
    if status != 200 or "access_token" not in answer:
        raise GoogleError(_("Google didn’t accept the sign-in: %(reason)s") % {"reason": _reason(answer, status)}, status)
    return answer


def signed_in_as(answer):
    """(address, domain) of the Google account that signed in, from the ID token in Google's answer.

    The token comes straight from Google's token address over HTTPS, so its contents can be
    read without checking its signature.
    """
    try:
        payload = answer.get("id_token", "").split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return "", ""
    return claims.get("email", ""), claims.get("hd", "")


def access_token(conn):
    token = cache.get(TOKEN_CACHE_KEY)
    if token:
        return token
    status, answer = http("POST", TOKEN_URL, form={
        "client_id": conn.client_id, "client_secret": conn.client_secret,
        "refresh_token": conn.refresh_token, "grant_type": "refresh_token",
    })
    if status != 200 or "access_token" not in answer:
        reconnect = answer.get("error") in ("invalid_grant", "invalid_client", "unauthorized_client")
        raise GoogleError(_("Google didn’t let the site sign in (%(reason)s). Connect Google again.") % {
            "reason": _reason(answer, status)}, status, reconnect=reconnect)
    cache.set(TOKEN_CACHE_KEY, answer["access_token"], max(60, int(answer.get("expires_in", 3600)) - 120))
    return answer["access_token"]


def forget_token():
    cache.delete(TOKEN_CACHE_KEY)


def revoke(conn):
    """Asks Google to cancel the site's access. Disconnecting works even if Google can't be reached."""
    if conn.refresh_token:
        try:
            http("POST", "https://oauth2.googleapis.com/revoke", form={"token": conn.refresh_token})
        except GoogleError:
            pass
    forget_token()


# ---------- accounts ----------

def temporary_password():
    """Like k7pm-x2qa-9tvh: easy to read out loud, and replaced by the person when they first sign in."""
    return "-".join("".join(secrets.choice(PASSWORD_LETTERS) for _ in range(4)) for _ in range(3))


def _when(value):
    if not value or value.startswith("1970-"):  # Google's way of saying "never"
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _inside(unit, parent):
    return unit == parent or unit.startswith(parent.rstrip("/") + "/")


@dataclass
class Account:
    email: str
    first_name: str
    last_name: str
    kind: str  # "staff", "volunteer", or "" for an account outside both units
    unit: str
    manager: str
    suspended: bool
    is_admin: bool
    last_login: datetime | None
    created: datetime | None
    manager_name: str = ""  # filled in when the manager's account is in the list too

    @property
    def name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    @property
    def can_change(self):
        """The site changes only staff and volunteer accounts, and never an administrator."""
        return bool(self.kind) and not self.is_admin


def to_account(user, conn):
    unit = user.get("orgUnitPath", "/")
    kind = "staff" if _inside(unit, conn.staff_unit) else "volunteer" if _inside(unit, conn.volunteer_unit) else ""
    manager = next((r.get("value", "") for r in user.get("relations") or [] if r.get("type") == "manager"), "")
    name = user.get("name") or {}
    return Account(
        email=user.get("primaryEmail", ""), first_name=name.get("givenName", ""), last_name=name.get("familyName", ""),
        kind=kind, unit=unit, manager=manager, suspended=bool(user.get("suspended")),
        is_admin=bool(user.get("isAdmin") or user.get("isDelegatedAdmin")),
        last_login=_when(user.get("lastLoginTime")), created=_when(user.get("creationTime")),
    )


UNIT_PATTERN = re.compile(r"^/[\w ./&-]*$")


class Directory:
    """Google Workspace user accounts in the staff and volunteer organizational units."""

    def __init__(self, conn):
        self.conn = conn

    def _call(self, method, url, body=None):
        status, answer = http(method, url, body=body, token=access_token(self.conn))
        if status == 401:  # the saved access token ran out early: get a new one and try once more
            forget_token()
            status, answer = http(method, url, body=body, token=access_token(self.conn))
        if status >= 400:
            raise GoogleError(_reason(answer, status), status)
        return answer

    def accounts(self):
        found = {}
        for unit in (self.conn.staff_unit, self.conn.volunteer_unit):
            page = ""
            while True:
                params = {"customer": "my_customer", "query": f"orgUnitPath='{unit}'", "maxResults": 500,
                          "orderBy": "email", "projection": "basic"}
                if page:
                    params["pageToken"] = page
                answer = self._call("GET", f"{USERS_URL}?{urlencode(params)}")
                for user in answer.get("users", []):
                    account = to_account(user, self.conn)
                    found[account.email.lower()] = account
                page = answer.get("nextPageToken", "")
                if not page:
                    break
        return sorted(found.values(), key=lambda a: (a.kind != "staff", a.last_name.lower(), a.first_name.lower()))

    def account(self, email):
        return to_account(self._call("GET", f"{USERS_URL}/{quote(email)}?projection=basic"), self.conn)

    def changeable(self, email):
        """The account, after checking it's one the site may change."""
        account = self.account(email)
        if not account.can_change:
            raise GoogleError(_("The site only changes staff and volunteer accounts, never administrators."))
        return account

    def create(self, *, email, first_name, last_name, kind, manager, password):
        body = {
            "primaryEmail": email,
            "name": {"givenName": first_name, "familyName": last_name},
            "password": password,
            "changePasswordAtNextLogin": True,
            "orgUnitPath": self.conn.unit_for(kind),
        }
        if manager:
            body["relations"] = [{"type": "manager", "value": manager}]
        return to_account(self._call("POST", USERS_URL, body), self.conn)

    def update(self, email, **fields):
        """Changes only the fields given. A field set to None is cleared."""
        return self._call("PUT", f"{USERS_URL}/{quote(email)}", fields)

    def delete(self, email):
        self._call("DELETE", f"{USERS_URL}/{quote(email)}")
