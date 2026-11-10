import base64
import json
import re
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role

from . import google
from .models import AccountChange, GoogleConnection

User = get_user_model()
MANAGE = reverse("accounts:manage")
CALLBACK = reverse("mailboxes:callback")
DOMAIN = "tahoeneighborhoodtable.com"
CLIENT_ID = "123-abc.apps.googleusercontent.com"
PASSWORD = re.compile(r"[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}")


def make_admin(username="boss"):
    user = User.objects.create_user(username, f"{username}@example.com", "x", first_name="Dana")
    user.profile.roles.add(Role.objects.get(slug=Role.ADMIN))
    user.refresh_from_db()
    return user


def id_token(email, hd):
    part = lambda data: base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()  # noqa: E731
    return ".".join([part({"alg": "RS256"}), part({"email": email, "hd": hd}), "signature"])


class FakeGoogle:
    """Stands in for Google's sign-in and Directory API, keeping user accounts in a dict."""

    def __init__(self):
        self.users = {}
        self.calls = []
        self.refresh_error = ""
        self.signed_in = ("website-admin@" + DOMAIN, DOMAIN)
        self.scope = "openid https://www.googleapis.com/auth/userinfo.email " + google.SCOPES[-1]

    def add(self, email, first, last, unit, admin=False, suspended=False, manager="", last_login="2026-11-01T17:00:00.000Z"):
        user = {"primaryEmail": email, "name": {"givenName": first, "familyName": last}, "orgUnitPath": unit,
                "isAdmin": admin, "suspended": suspended, "lastLoginTime": last_login,
                "creationTime": "2026-10-01T17:00:00.000Z"}
        if manager:
            user["relations"] = [{"type": "manager", "value": manager}]
        self.users[email] = user

    def __call__(self, method, url, *, form=None, body=None, token=None):
        self.calls.append((method, url, form, body, token))
        if url == google.TOKEN_URL:
            if form["grant_type"] == "authorization_code":
                return 200, {"access_token": "access-1", "expires_in": 3599, "refresh_token": "refresh-1",
                             "scope": self.scope, "id_token": id_token(*self.signed_in)}
            if self.refresh_error:
                return 400, {"error": self.refresh_error, "error_description": "Token has been expired or revoked."}
            return 200, {"access_token": "access-2", "expires_in": 3599}
        if url.startswith("https://oauth2.googleapis.com/revoke"):
            return 200, {}
        assert url.startswith(google.USERS_URL) and token, url
        rest = url[len(google.USERS_URL):]
        if method == "GET" and rest.startswith("?"):
            unit = parse_qs(urlsplit(url).query)["query"][0].split("'")[1]
            users = [u for u in self.users.values()
                     if u["orgUnitPath"] == unit or u["orgUnitPath"].startswith(unit + "/")]
            return 200, ({"users": users} if users else {})
        if method == "POST":
            if body["primaryEmail"] in self.users:
                return 409, {"error": {"code": 409, "message": "Entity already exists."}}
            user = {k: v for k, v in body.items() if k != "password"}
            user.update(isAdmin=False, suspended=False, lastLoginTime="1970-01-01T00:00:00.000Z")
            self.users[body["primaryEmail"]] = user
            return 200, user
        email = unquote(rest.lstrip("/").split("?")[0])
        if email not in self.users:
            return 404, {"error": {"code": 404, "message": "Resource Not Found: userKey"}}
        if method == "GET":
            return 200, self.users[email]
        if method == "PUT":
            for key, value in body.items():
                if value is None:
                    self.users[email].pop(key, None)
                elif key != "password":
                    self.users[email][key] = value
            return 200, self.users[email]
        if method == "DELETE":
            del self.users[email]
            return 204, {}
        raise AssertionError(method)

    def sent(self, method):
        return [call for call in self.calls if call[0] == method and call[1].startswith(google.USERS_URL)]


@mock.patch("emails.dns.lookup", lambda name, record_type: [])
class MailboxTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        self.client.force_login(self.admin)
        self.google = FakeGoogle()
        patcher = mock.patch("mailboxes.google.http", self.google)
        patcher.start()
        self.addCleanup(patcher.stop)

    def connect(self):
        conn = GoogleConnection.load()
        conn.client_id = CLIENT_ID
        conn.set_client_secret("GOCSPX-secret")
        conn.set_refresh_token("refresh-1")
        conn.connected_as = "website-admin@" + DOMAIN
        conn.save()
        self.google.add("maria@" + DOMAIN, "Maria", "Lopez", "/Staff")
        self.google.add("jane@" + DOMAIN, "Jane", "Kim", "/Volunteers", manager="maria@" + DOMAIN)
        self.google.add("dana@" + DOMAIN, "Dana", "Admin", "/Staff", admin=True)
        return conn

    def post(self, **data):
        return self.client.post(MANAGE, data)

    def page(self):
        return self.client.get(MANAGE).content.decode()

    # ---------- connecting ----------

    def test_before_connecting_the_page_explains_the_steps(self):
        html = self.page()
        self.assertIn("Connect Google Workspace", html)
        self.assertIn("https://tahoeneighborhoodtable.com/dashboard/manage/google/callback/", html)
        self.assertIn("User Management Admin", html)
        self.assertIn("Connect Google Workspace to create and manage staff and volunteer email accounts here.", html)
        self.assertNotIn('value="google-connect"', html)

    def test_saving_the_oauth_client(self):
        response = self.post(action="google-settings", client_id="not-an-id", client_secret="GOCSPX-secret",
                             domain=DOMAIN, staff_unit="/Staff", volunteer_unit="/Volunteers")
        self.assertContains(response, "It ends in .apps.googleusercontent.com.")
        response = self.post(action="google-settings", client_id=CLIENT_ID, client_secret=" GOCSPX-secret ",
                             domain="@TahoeNeighborhoodTable.com", staff_unit="Staff", volunteer_unit="/Volunteers/")
        self.assertRedirects(response, f"{MANAGE}#mailboxes", fetch_redirect_response=False)
        conn = GoogleConnection.load()
        self.assertEqual((conn.client_id, conn.domain, conn.staff_unit, conn.volunteer_unit),
                         (CLIENT_ID, DOMAIN, "/Staff", "/Volunteers"))
        self.assertEqual(conn.client_secret, "GOCSPX-secret")
        self.assertNotIn("GOCSPX-secret", conn.client_secret_encrypted)
        html = self.page()
        self.assertIn("Now choose Connect Google", html)
        self.assertIn('value="google-connect"', html)
        self.assertNotIn("GOCSPX-secret", html)

    def test_staff_and_volunteers_need_separate_units(self):
        response = self.post(action="google-settings", client_id=CLIENT_ID, client_secret="GOCSPX-secret",
                             domain=DOMAIN, staff_unit="/Team", volunteer_unit="/Team/Volunteers")
        self.assertContains(response, "Staff and volunteers need separate organizational units.")

    def test_connecting(self):
        self.post(action="google-settings", client_id=CLIENT_ID, client_secret="GOCSPX-secret", domain=DOMAIN,
                  staff_unit="/Staff", volunteer_unit="/Volunteers")
        response = self.post(action="google-connect")
        url = urlsplit(response["Location"])
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", google.AUTH_URL)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.assertEqual(params["client_id"], CLIENT_ID)
        self.assertEqual(params["redirect_uri"], "https://tahoeneighborhoodtable.com" + CALLBACK)
        self.assertIn(google.SCOPES[-1], params["scope"].split())
        self.assertNotIn("gmail", params["scope"])
        self.assertEqual((params["access_type"], params["code_challenge_method"], params["hd"]),
                         ("offline", "S256", DOMAIN))

        done = self.client.get(CALLBACK, {"state": params["state"], "code": "code-1"})
        self.assertRedirects(done, f"{MANAGE}#mailboxes", fetch_redirect_response=False)
        exchange = next(call for call in self.google.calls if call[1] == google.TOKEN_URL)
        self.assertEqual(exchange[2]["code"], "code-1")
        self.assertTrue(exchange[2]["code_verifier"])
        conn = GoogleConnection.load()
        self.assertEqual((conn.connected_as, conn.refresh_token), ("website-admin@" + DOMAIN, "refresh-1"))
        self.assertNotIn("refresh-1", conn.refresh_token_encrypted)
        self.assertIn("Connected to Google Workspace as website-admin@tahoeneighborhoodtable.com.", self.page())

    def test_a_stale_or_foreign_sign_in_is_refused(self):
        self.post(action="google-settings", client_id=CLIENT_ID, client_secret="GOCSPX-secret", domain=DOMAIN,
                  staff_unit="/Staff", volunteer_unit="/Volunteers")
        self.client.get(CALLBACK, {"state": "made-up", "code": "code-1"})
        self.assertIn("That sign-in was out of date.", self.page())

        state = lambda: parse_qs(urlsplit(self.post(action="google-connect")["Location"]).query)["state"][0]  # noqa: E731
        self.google.signed_in = ("someone@gmail.com", "")
        self.client.get(CALLBACK, {"state": state(), "code": "code-1"})
        self.assertIn("Sign in with the website’s admin account at tahoeneighborhoodtable.com, not someone@gmail.com.",
                      self.page())

        self.google.signed_in = ("website-admin@" + DOMAIN, DOMAIN)
        self.google.scope = "openid email"
        self.client.get(CALLBACK, {"state": state(), "code": "code-1"})
        self.assertIn("Google didn’t give the site permission to manage user accounts.", self.page())

        self.client.get(CALLBACK, {"state": state(), "error": "access_denied"})
        self.assertIn("Google didn’t connect: access_denied", self.page())
        self.assertFalse(GoogleConnection.load().is_connected)

    # ---------- accounts ----------

    def test_the_accounts(self):
        self.connect()
        html = self.page()
        for text in ("Maria Lopez", "jane@tahoeneighborhoodtable.com", "Google admin", "3 accounts",
                     "Staff: 2 · Volunteers: 1", "This is a Google admin account."):
            self.assertIn(text, html)
        self.assertIn("<td>Maria Lopez</td>", html)  # Jane's manager, by name
        self.assertIn("3 accounts.", html)  # the tile

    def test_the_access_token_is_reused(self):
        self.connect()
        self.page()
        self.page()
        refreshes = [call for call in self.google.calls if call[1] == google.TOKEN_URL]
        self.assertEqual(len(refreshes), 1)

    def test_creating_an_account(self):
        self.connect()
        response = self.post(action="account-create", first_name="Sam", last_name="Lee", username="Sam.Lee",
                             kind="volunteer", manager="maria@" + DOMAIN, agreed="on")
        self.assertRedirects(response, f"{MANAGE}#mailboxes", fetch_redirect_response=False)
        user = self.google.users["sam.lee@" + DOMAIN]
        self.assertEqual(user["orgUnitPath"], "/Volunteers")
        self.assertTrue(user["changePasswordAtNextLogin"])
        self.assertEqual(user["relations"], [{"type": "manager", "value": "maria@" + DOMAIN}])
        password = self.google.sent("POST")[0][3]["password"]
        self.assertRegex(password, PASSWORD)

        html = self.page()
        self.assertIn("Created sam.lee@tahoeneighborhoodtable.com.", html)
        self.assertIn(password, html)
        self.assertNotIn(password, self.page())  # shown once
        change = AccountChange.objects.get()
        self.assertEqual((change.action, change.address, change.by), (AccountChange.CREATED, "sam.lee@" + DOMAIN, self.admin))
        self.assertEqual((change.kind, change.manager), ("volunteer", "maria@" + DOMAIN))
        self.assertIn("Volunteer · manager maria@tahoeneighborhoodtable.com", self.page())

    def test_a_new_account_needs_agreement_and_a_good_address(self):
        self.connect()
        response = self.post(action="account-create", first_name="Sam", last_name="Lee", username="sam lee",
                             kind="volunteer", manager="")
        self.assertContains(response, "Use letters, numbers, dots, dashes or underscores")
        self.assertContains(response, "Get their written agreement before creating the account.")
        response = self.post(action="account-create", first_name="Sam", last_name="Lee", username="sam@gmail.com",
                             kind="volunteer", manager="", agreed="on")
        self.assertContains(response, "The address has to end in @tahoeneighborhoodtable.com.")
        response = self.post(action="account-create", first_name="Sam", last_name="Lee", username="sam",
                             kind="volunteer", manager="jane@" + DOMAIN, agreed="on")
        self.assertContains(response, "Select a valid choice.")  # managers are staff, and Jane is a volunteer
        self.assertFalse(self.google.sent("POST"))

    def test_an_address_thats_taken(self):
        self.connect()
        self.post(action="account-create", first_name="Jane", last_name="Kim", username="jane", kind="volunteer",
                  manager="", agreed="on")
        self.assertIn("Google said: Entity already exists.", self.page())
        self.assertFalse(AccountChange.objects.exists())

    def test_suspending_and_restoring(self):
        self.connect()
        self.post(action="account-suspend", email="jane@" + DOMAIN)
        self.assertTrue(self.google.users["jane@" + DOMAIN]["suspended"])
        html = self.page()
        self.assertIn("Suspended jane@tahoeneighborhoodtable.com.", html)
        self.assertIn("1 suspended.", html)
        self.post(action="account-restore", email="jane@" + DOMAIN)
        self.assertFalse(self.google.users["jane@" + DOMAIN]["suspended"])
        self.assertEqual(list(AccountChange.objects.values_list("action", flat=True)),
                         [AccountChange.RESTORED, AccountChange.SUSPENDED])

    def test_resetting_a_password(self):
        self.connect()
        self.post(action="account-password", email="jane@" + DOMAIN)
        body = self.google.sent("PUT")[0][3]
        self.assertTrue(body["changePasswordAtNextLogin"])
        self.assertIn(body["password"], self.page())

    def test_changing_kind_and_manager(self):
        self.connect()
        self.post(action="account-change", email="jane@" + DOMAIN, kind="staff", manager="")
        user = self.google.users["jane@" + DOMAIN]
        self.assertEqual(user["orgUnitPath"], "/Staff")
        self.assertNotIn("relations", user)
        change = AccountChange.objects.get()
        self.assertEqual((change.action, change.kind, change.manager), (AccountChange.CHANGED, "staff", ""))
        self.assertIn("Staff · no manager", self.page())

    def test_deleting_needs_the_address_typed(self):
        self.connect()
        self.post(action="account-delete", email="jane@" + DOMAIN, confirm="jane")
        self.assertIn("jane@" + DOMAIN, self.google.users)
        self.assertIn("Not deleted. To delete jane@tahoeneighborhoodtable.com, type its address exactly.", self.page())
        self.post(action="account-delete", email="jane@" + DOMAIN, confirm=" Jane@TahoeNeighborhoodTable.com ")
        self.assertNotIn("jane@" + DOMAIN, self.google.users)
        self.assertIn("a Google admin can still restore it", self.page())

    def test_admins_and_other_accounts_are_left_alone(self):
        self.connect()
        self.google.add("board@" + DOMAIN, "Board", "Chair", "/Board")
        for email in ("dana@" + DOMAIN, "board@" + DOMAIN):
            self.post(action="account-suspend", email=email)
            self.post(action="account-delete", email=email, confirm=email)
        self.assertFalse(self.google.sent("PUT") or self.google.sent("DELETE"))
        self.assertIn("never administrators", self.page())
        self.assertNotIn("board@", self.page())

    def test_when_google_signs_the_site_out(self):
        self.connect()
        self.google.refresh_error = "invalid_grant"
        html = self.page()
        self.assertIn("Connect Google again.", html)
        self.assertIn("Google didn’t answer. See Staff and volunteer email.", html)
        self.assertIn("The accounts couldn’t be loaded.", html)

    def test_disconnecting(self):
        self.connect()
        self.post(action="google-disconnect")
        conn = GoogleConnection.load()
        self.assertFalse(conn.is_connected)
        self.assertTrue(conn.is_set_up)
        self.assertTrue(any("revoke" in call[1] for call in self.google.calls))
        self.assertIn("Disconnected.", self.page())

    def test_only_admins(self):
        self.connect()
        User.objects.create_user("sam", "sam@example.com", "x")
        self.client.login(username="sam", password="x")
        self.assertEqual(self.client.get(CALLBACK, {"state": "x", "code": "y"}).status_code, 403)
        self.assertEqual(self.post(action="account-delete", email="jane@" + DOMAIN, confirm="jane@" + DOMAIN).status_code, 403)
        self.assertIn("jane@" + DOMAIN, self.google.users)

    def test_the_section_in_spanish(self):
        self.connect()
        self.client.post(reverse("set_language"), {"language": "es", "next": "/"})
        html = self.page()
        self.assertTrue("Correo del personal y voluntarios" in html, "The section isn’t in Spanish")


class GoogleHelperTests(TestCase):
    def test_temporary_passwords(self):
        passwords = {google.temporary_password() for _ in range(50)}
        self.assertEqual(len(passwords), 50)
        for password in passwords:
            self.assertRegex(password, rf"^{PASSWORD.pattern}$")

    def test_reading_an_account(self):
        conn = GoogleConnection(staff_unit="/Staff", volunteer_unit="/Volunteers")
        account = google.to_account({"primaryEmail": "a@x.org", "orgUnitPath": "/Volunteers/North",
                                     "lastLoginTime": "1970-01-01T00:00:00.000Z",
                                     "creationTime": "2026-10-01T17:00:00.000Z"}, conn)
        self.assertEqual((account.kind, account.last_login, account.name), ("volunteer", None, "a@x.org"))
        self.assertEqual(account.created.year, 2026)
        self.assertEqual(google.to_account({"orgUnitPath": "/Board"}, conn).kind, "")
