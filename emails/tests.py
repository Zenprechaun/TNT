import json
import smtplib
import socket
import ssl
import tempfile
from datetime import time, timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from donations.models import Donation
from volunteers.models import Assignment, Event, Shift, Signup
from volunteers.models import Role as ShiftRole

from . import dns, sending
from .models import Email, EmailSettings
from .secrets import decrypt, encrypt

User = get_user_model()
MANAGE = reverse("accounts:manage")
ON = {"EMAIL_HOST": "smtp.example.org"}


def make_admin(username="boss"):
    user = User.objects.create_user(username, f"{username}@example.com", "x", first_name="Dana")
    user.profile.roles.add(Role.objects.get(slug=Role.ADMIN))
    user.refresh_from_db()
    return user


def no_dns(name, record_type):
    return []


class SecretTests(TestCase):
    def test_the_key_is_stored_encrypted(self):
        token = encrypt("re_abc123")
        self.assertNotIn("re_abc123", token)
        self.assertEqual(decrypt(token), "re_abc123")

    def test_a_different_secret_key_cant_read_it(self):
        token = encrypt("re_abc123")
        with override_settings(SECRET_KEY="another-secret-key"):
            self.assertEqual(decrypt(token), "")
            conf = EmailSettings(password_encrypted=token)
            self.assertTrue(conf.password_unreadable)


class ConnectionTests(TestCase):
    def test_email_is_off_without_settings(self):
        self.assertIsNone(sending.current_connection())
        self.assertFalse(sending.is_on())
        self.assertFalse(sending.will_send(Email.VOLUNTEER))

    @override_settings(**ON)
    def test_the_servers_settings_file_works_too(self):
        connection = sending.current_connection()
        self.assertEqual((connection.host, connection.source), ("smtp.example.org", "server"))

    @override_settings(**ON)
    def test_the_management_page_settings_come_first(self):
        conf = EmailSettings.load()
        conf.service, conf.host, conf.port, conf.security, conf.username = "resend", "smtp.resend.com", 465, "ssl", "resend"
        conf.set_password("re_abcdefghijkl")
        conf.save()
        connection = sending.current_connection()
        self.assertEqual((connection.host, connection.port, connection.use_ssl, connection.use_tls, connection.source),
                         ("smtp.resend.com", 465, True, False, "site"))
        self.assertEqual(connection.password, "re_abcdefghijkl")
        self.assertEqual(conf.password_end, "ijkl")

    @override_settings(**ON)
    def test_each_kind_can_be_turned_off(self):
        conf = EmailSettings.load()
        conf.volunteer_confirmations = conf.donation_receipts = False
        conf.volunteer_notify = ""
        conf.save()
        self.assertFalse(sending.will_send(Email.VOLUNTEER))
        self.assertFalse(sending.will_send(Email.RECEIPT))
        self.assertFalse(sending.will_send(Email.ORGANIZER))
        self.assertTrue(sending.will_send(Email.PASSWORD))

    @override_settings(VOLUNTEER_NOTIFY_EMAILS=["a@example.org", "b@example.org"])
    def test_the_organizer_list_starts_from_the_settings_file(self):
        self.assertEqual(EmailSettings.load().notify_list, ["a@example.org", "b@example.org"])


class SendTests(TestCase):
    def test_with_email_off_nothing_goes_out_but_a_copy_is_kept(self):
        record = sending.send(Email.TEST, "maya@example.com", "Hello", "Body")
        self.assertEqual(record.status, Email.OFF)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Email.objects.get().body, "Body")

    @override_settings(**ON)
    def test_sending(self):
        record = sending.send(Email.TEST, ["maya@example.com", "sam@example.com"], "Hello  there", "Body", ref="test")
        self.assertEqual(record.status, Email.SENT)
        self.assertIsNotNone(record.sent_at)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["maya@example.com", "sam@example.com"])
        self.assertEqual(message.from_email, "Tahoe Neighborhood Table <info@tahoeneighborhoodtable.com>")
        self.assertEqual(message.reply_to, ["info@tahoeneighborhoodtable.com"])
        self.assertEqual(message.subject, "Hello there")

    @override_settings(**ON)
    def test_a_failure_is_recorded_with_the_services_answer(self):
        error = smtplib.SMTPAuthenticationError(535, b"Invalid API key")
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=error):
            record = sending.send(Email.TEST, "maya@example.com", "Hello", "Body")
        self.assertEqual((record.status, record.problem, record.error), (Email.FAILED, "login", "535 Invalid API key"))
        self.assertIn("API key", str(record.problem_text))

    @override_settings(**ON)
    def test_password_links_arent_kept(self):
        record = sending.send(Email.PASSWORD, "maya@example.com", "Reset", "https://example.org/secret-link")
        self.assertEqual(Email.objects.get(pk=record.pk).body, "")
        self.assertFalse(record.can_send_again)
        self.assertIn("secret-link", mail.outbox[0].body)

    @override_settings(**ON)
    def test_old_copies_are_deleted(self):
        old = Email.objects.create(kind=Email.TEST, to="a@example.org", subject="Old", status=Email.SENT)
        Email.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=200))
        sending.send(Email.TEST, "maya@example.com", "New", "Body")
        self.assertEqual(list(Email.objects.values_list("subject", flat=True)), ["New"])

    def test_sending_again_once_email_is_on(self):
        record = sending.send(Email.TEST, "maya@example.com", "Hello", "Body")
        self.assertEqual(record.status, Email.OFF)
        with override_settings(**ON):
            self.assertTrue(sending.send_again(record))
        record.refresh_from_db()
        self.assertEqual((record.status, record.attempts), (Email.SENT, 1))
        self.assertEqual(mail.outbox[0].body, "Body")

    def test_problems_are_told_apart(self):
        cases = [
            (smtplib.SMTPSenderRefused(550, b"Domain not verified", "info@x.org"), "sender", "550 Domain not verified"),
            (smtplib.SMTPRecipientsRefused({"a@x.org": (550, b"No such user")}), "recipient", "a@x.org: 550 No such user"),
            (smtplib.SMTPDataError(450, b"Daily limit reached"), "refused", "450 Daily limit reached"),
            (ssl.SSLError("wrong version number"), "tls", None),
            (socket.timeout("timed out"), "timeout", "timed out"),
            (socket.gaierror(-2, "Name or service not known"), "connect", None),
            (ConnectionRefusedError(111, "Connection refused"), "connect", None),
            (ValueError("odd"), "other", "odd"),
        ]
        for exc, problem, details in cases:
            with self.subTest(exc=exc):
                found, text = sending.describe(exc)
                self.assertEqual(found, problem)
                if details:
                    self.assertEqual(text, details)


@override_settings(**ON, VOLUNTEER_NOTIFY_EMAILS=["boss@example.org"])
class EmailsFromTheSiteTests(TestCase):
    """Volunteer and donation emails are kept, and receipts note when they went out."""

    def setUp(self):
        Event.objects.all().delete()
        ShiftRole.objects.all().delete()
        role = ShiftRole.objects.create(name="Kitchen crew")
        self.event = Event.objects.create(name="Community Dinner", slug="dinner")
        self.shift = Shift.objects.create(event=self.event, role=role, date=timezone.localdate() + timedelta(days=5),
                                          start=time(8), end=time(11), capacity=3)
        self.signup = Signup.objects.create(event=self.event, first_name="Maya", last_name="Okafor",
                                            email="maya@example.com", phone="530 555 0142")
        Assignment.objects.create(signup=self.signup, shift=self.shift)

    def test_a_sign_up_keeps_both_emails(self):
        from volunteers.services import send_emails

        send_emails(self.signup.pk)
        kinds = sorted(Email.objects.values_list("kind", "to", "ref"))
        self.assertEqual(kinds, [(Email.ORGANIZER, "boss@example.org", f"signup:{self.signup.pk}"),
                                 (Email.VOLUNTEER, "maya@example.com", f"signup:{self.signup.pk}")])

    def test_with_email_off_the_sign_up_emails_wait(self):
        from volunteers.services import send_emails

        with override_settings(EMAIL_HOST=""):
            send_emails(self.signup.pk)
        self.assertEqual(set(Email.objects.values_list("status", flat=True)), {Email.OFF})
        self.assertEqual(len(mail.outbox), 0)

    def test_a_receipt_sent_later_is_noted_on_the_donation(self):
        from donations.services import send_receipt

        donation = Donation.objects.create(amount=5000, email="maya@example.com", name="Maya Okafor",
                                           status=Donation.PAID, paid_at=timezone.now())
        with override_settings(EMAIL_HOST=""):
            send_receipt(donation.pk)
        donation.refresh_from_db()
        self.assertIsNone(donation.receipt_sent_at)
        record = Email.objects.get(kind=Email.RECEIPT)
        self.assertEqual((record.status, record.ref), (Email.OFF, f"donation:{donation.pk}"))

        self.assertTrue(sending.send_again(record))
        donation.refresh_from_db()
        self.assertIsNotNone(donation.receipt_sent_at)
        self.assertIn("Thank you for your donation of $50", mail.outbox[0].body)

    def test_receipts_can_be_turned_off(self):
        from donations.services import send_receipt

        conf = EmailSettings.load()
        conf.donation_receipts = False
        conf.save()
        donation = Donation.objects.create(amount=5000, email="maya@example.com", status=Donation.PAID,
                                           paid_at=timezone.now())
        send_receipt(donation.pk)
        self.assertFalse(Email.objects.exists())


@mock.patch("emails.dns.lookup", no_dns)
class ManagementPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        self.client.force_login(self.admin)

    def post(self, **data):
        return self.client.post(MANAGE, data)

    def connect_resend(self, key="re_test_1234567890"):
        return self.post(action="connect", service="resend", password=key, from_name="Tahoe Neighborhood Table",
                         from_address="info@tahoeneighborhoodtable.com", reply_to="info@tahoeneighborhoodtable.com")

    def test_only_admins_see_it(self):
        self.client.logout()
        self.assertRedirects(self.client.get(MANAGE), f"{reverse('accounts:login')}?next={MANAGE}")
        User.objects.create_user("sam", "sam@example.com", "x")
        self.client.login(username="sam", password="x")
        self.assertEqual(self.client.get(MANAGE).status_code, 403)
        self.assertEqual(self.post(action="disconnect").status_code, 403)

    def test_the_page(self):
        html = self.client.get(MANAGE).content.decode()
        for part in ('id="email"', 'id="volunteers"', 'id="donations"', 'id="site"', "Running the site",
                     "Create a free account at", "No emails yet.", "Backups run on the live server."):
            self.assertIn(part, html)
        self.assertIn(f'href="{MANAGE}" aria-current="page"', html)
        self.assertIn("No mail server receives email for tahoeneighborhoodtable.com", html)

    def test_connecting_resend(self):
        response = self.connect_resend()
        self.assertRedirects(response, f"{MANAGE}#email-test", fetch_redirect_response=False)
        conf = EmailSettings.load()
        self.assertEqual((conf.service, conf.host, conf.port, conf.security, conf.username),
                         ("resend", "smtp.resend.com", 465, "ssl", "resend"))
        self.assertEqual(conf.password, "re_test_1234567890")
        self.assertNotIn("re_test_1234567890", conf.password_encrypted)
        self.assertIsNotNone(conf.connected_at)
        self.assertEqual(conf.updated_by, self.admin)
        html = self.client.get(MANAGE).content.decode()
        self.assertIn("Email is on. The site signed in to Resend.", html)
        self.assertIn("Saved, ends in …7890", html)
        self.assertNotIn("re_test_1234567890", html)
        self.assertTrue(sending.is_on())

    def test_a_key_thats_not_from_resend(self):
        response = self.connect_resend(key="sk_live_oops")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A Resend API key starts with re_.")
        self.assertFalse(EmailSettings.load().host)

    def test_the_key_is_needed_the_first_time_only(self):
        self.assertContains(self.connect_resend(key=""), "Paste the API key or password")
        self.connect_resend()
        self.connect_resend(key="")
        self.assertEqual(EmailSettings.load().password, "re_test_1234567890")

    def test_another_service_needs_its_server(self):
        response = self.post(action="connect", service="other", username="me", password="pw", host="", port="",
                             security="starttls", from_name="TNT", from_address="info@tahoeneighborhoodtable.com")
        self.assertContains(response, "Enter the SMTP server")
        self.post(action="connect", service="other", username="me", password="pw", host="mail.example.org",
                  port="", security="starttls", from_name="TNT", from_address="info@tahoeneighborhoodtable.com")
        conf = EmailSettings.load()
        self.assertEqual((conf.host, conf.port, conf.security), ("mail.example.org", 587, "starttls"))

    def test_when_the_service_turns_down_the_login(self):
        with mock.patch("emails.manage.check_login", return_value=("login", "535 Invalid API key")):
            self.connect_resend()
        html = self.client.get(MANAGE).content.decode()
        self.assertIn("Saved, but the site couldn’t sign in to the email service.", html)
        self.assertIn("535 Invalid API key", html)
        self.assertIsNone(EmailSettings.load().connected_at)

    def test_choosing_what_the_site_emails(self):
        response = self.post(action="choices", donation_receipts="on", volunteer_notify="boss@example.org\nnot-an-address")
        self.assertContains(response, "These aren’t email addresses: not-an-address")
        self.post(action="choices", donation_receipts="on",
                  volunteer_notify="boss@example.org, Boss@example.org\nkim@example.org")
        conf = EmailSettings.load()
        self.assertFalse(conf.volunteer_confirmations)
        self.assertTrue(conf.donation_receipts)
        self.assertEqual(conf.notify_list, ["boss@example.org", "kim@example.org"])

    def test_a_test_email(self):
        self.post(action="test", to="dana@example.com")
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("Connect an email service first.", self.client.get(MANAGE).content.decode())

        self.connect_resend()
        self.assertRedirects(self.post(action="test", to="dana@example.com"), f"{MANAGE}#email-test",
                             fetch_redirect_response=False)
        self.assertEqual(mail.outbox[0].to, ["dana@example.com"])
        self.assertIn("Sent by Dana from the Management page.", mail.outbox[0].body)
        html = self.client.get(MANAGE).content.decode()
        self.assertIn("Sent a test email to dana@example.com.", html)
        self.assertIn("Test email from Tahoe Neighborhood Table", html)

    def test_sending_an_email_again(self):
        record = sending.send(Email.TEST, "maya@example.com", "Waiting", "Body")
        self.assertContains(self.client.get(MANAGE), "Not sent: email was off")
        self.connect_resend()
        self.post(action="send-again", email=record.pk)
        record.refresh_from_db()
        self.assertEqual(record.status, Email.SENT)
        self.assertIn("Sent “Waiting” again to maya@example.com.", self.client.get(MANAGE).content.decode())

        self.assertEqual(self.post(action="send-again", email="abc").status_code, 404)
        reset = Email.objects.create(kind=Email.PASSWORD, to="maya@example.com", subject="Reset", status=Email.FAILED)
        self.post(action="send-again", email=reset.pk)
        self.assertIn("This email can’t be sent again.", self.client.get(MANAGE).content.decode())

    def test_stopping_email(self):
        self.connect_resend()
        self.post(action="disconnect")
        conf = EmailSettings.load()
        self.assertEqual((conf.host, conf.password_encrypted), ("", ""))
        self.assertFalse(sending.is_on())

    def test_the_domains_records(self):
        found = {"tahoeneighborhoodtable.com": ["mx1.mailhost.example"],
                 "_dmarc.tahoeneighborhoodtable.com": ["v=DMARC1; p=none;"],
                 "resend._domainkey.tahoeneighborhoodtable.com": ["p=MIGfMA0"]}
        self.connect_resend()
        cache.clear()
        with mock.patch("emails.dns.lookup", lambda name, record_type: found.get(name, [])):
            html = self.client.get(MANAGE).content.decode()
        self.assertIn("Received by mx1.mailhost.example", html)
        self.assertIn("In place: v=DMARC1; p=none;", html)
        self.assertIn("Email signature (DKIM)", html)

    def test_when_dns_cant_be_checked(self):
        def broken(name, record_type):
            raise dns.LookupFailed("no network")

        cache.clear()
        with mock.patch("emails.dns.lookup", broken):
            self.assertContains(self.client.get(MANAGE), "Couldn’t check DNS just now.")

    def test_the_status_tiles(self):
        with tempfile.TemporaryDirectory() as folder:
            status_file = Path(folder) / "publish-status.json"
            status_file.write_text(json.dumps({"revision": "abc1234def", "state": "failed", "step": "migrate",
                                               "message": "Database update failed", "finished_at": "2026-11-09T20:00:00+00:00"}))
            backups = Path(folder) / "backups"
            backups.mkdir()
            (backups / "db-2026-11-09-020000.sqlite3").write_bytes(b"x" * 2048)
            with override_settings(PUBLISH_STATUS_FILE=status_file, BACKUP_DIR=backups):
                html = self.client.get(MANAGE).content.decode()
        self.assertIn("The last update didn’t go live.", html)
        self.assertIn("Database update failed", html)
        self.assertIn("1 copy kept.", html)
        self.assertIn("Connect an email service so the site can send receipts", html)
        self.assertIn("Stripe isn’t connected, so the Donate button opens an email.", html)
        self.assertIn("Last update", html)

    def test_the_events_and_their_roster(self):
        Event.objects.all().delete()
        role, _ = ShiftRole.objects.get_or_create(name="Serving line")
        event = Event.objects.create(name="Winter Supper", slug="supper")
        shift = Shift.objects.create(event=event, role=role, date=timezone.localdate() + timedelta(days=3),
                                     start=time(17), end=time(20), capacity=4)
        signup = Signup.objects.create(event=event, first_name="Ana", last_name="Ruiz", email="ana@example.com",
                                       phone="530 555 0199")
        Assignment.objects.create(signup=signup, shift=shift)
        html = self.client.get(MANAGE).content.decode()
        self.assertIn("Winter Supper", html)
        self.assertIn("1 of 4", html)
        self.assertIn("1 volunteer", html)
        roster = self.client.get(reverse("accounts:manage_roster", args=[event.pk]))
        self.assertEqual(roster["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Ana,Ruiz,ana@example.com", roster.content.decode())

    def test_the_full_list_in_the_admin_site(self):
        record = sending.send(Email.TEST, "maya@example.com", "Waiting", "Body")
        self.assertContains(self.client.get(reverse("admin:emails_email_changelist")), "Waiting")
        page = self.client.get(reverse("admin:emails_email_change", args=[record.pk]))
        self.assertContains(page, "Not sent: email was off")
        self.assertNotContains(page, 'name="_save"')

    def test_downloading_a_years_donations(self):
        Donation.objects.create(amount=2500, name="Maya Okafor", email="maya@example.com", status=Donation.PAID,
                                paid_at=timezone.now())
        year = timezone.localdate().year
        response = self.client.get(reverse("accounts:manage_donations_csv", args=[year]))
        self.assertIn("Maya Okafor,maya@example.com,25.0", response.content.decode())
        self.assertEqual(self.client.get(reverse("accounts:manage_donations_csv", args=[1999])).status_code, 404)


@mock.patch("emails.dns.lookup", no_dns)
class SpanishManagementTests(TestCase):
    def test_the_page_in_spanish(self):
        self.client.force_login(make_admin())
        self.client.post(reverse("set_language"), {"language": "es", "next": "/"})
        html = self.client.get(MANAGE).content.decode()
        self.assertTrue('<html lang="es">' in html and "<title>Gestión · Tahoe Neighborhood Table</title>" in html,
                        "The Management page isn’t in Spanish")


class PasswordResetTests(TestCase):
    FORGOT = reverse("accounts:password_forgot")

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("maya@example.com", "maya@example.com", "old-password-123",
                                             first_name="Maya")

    def test_without_email_it_says_whom_to_ask(self):
        html = self.client.get(self.FORGOT).content.decode()
        self.assertIn("The site can’t email reset links yet.", html)
        self.assertNotIn("Forgot your password?", self.client.get(reverse("accounts:login")).content.decode())
        self.client.post(self.FORGOT, {"email": "maya@example.com"})
        self.assertFalse(Email.objects.exists())

    @override_settings(**ON)
    def test_resetting_a_password(self):
        self.assertContains(self.client.get(reverse("accounts:login")), "Forgot your password?")
        response = self.client.post(self.FORGOT, {"email": "Maya@Example.com"})
        self.assertRedirects(response, reverse("accounts:password_reset_sent"))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, "Choose a new password for Tahoe Neighborhood Table")
        self.assertIn("Hi Maya,", message.body)
        record = Email.objects.get()
        self.assertEqual((record.kind, record.body, record.ref), (Email.PASSWORD, "", f"user:{self.user.pk}"))

        link = next(line for line in message.body.splitlines() if "/accounts/password/reset/" in line)
        page = self.client.get(link.replace("http://testserver", ""), follow=True)
        self.assertContains(page, "Choose a new password")
        form_url = page.redirect_chain[-1][0]
        done = self.client.post(form_url, {"new_password1": "a-brand-new-pass-42", "new_password2": "a-brand-new-pass-42"})
        self.assertRedirects(done, reverse("accounts:dashboard"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("a-brand-new-pass-42"))

        # The link works once.
        self.client.logout()
        self.assertContains(self.client.get(link.replace("http://testserver", ""), follow=True),
                            "This link doesn’t work anymore")

    @override_settings(**ON)
    def test_an_unknown_address_looks_the_same(self):
        response = self.client.post(self.FORGOT, {"email": "nobody@example.com"})
        self.assertRedirects(response, reverse("accounts:password_reset_sent"))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(**ON)
    def test_mismatched_passwords(self):
        self.client.post(self.FORGOT, {"email": "maya@example.com"})
        link = next(line for line in mail.outbox[0].body.splitlines() if "/accounts/password/reset/" in line)
        page = self.client.get(link.replace("http://testserver", ""), follow=True)
        response = self.client.post(page.redirect_chain[-1][0], {"new_password1": "a-brand-new-pass-42",
                                                                 "new_password2": "something-else-42"})
        self.assertContains(response, "The two passwords don’t match.")

    @override_settings(**ON)
    def test_too_many_requests(self):
        for _ in range(5):
            self.client.post(self.FORGOT, {"email": "maya@example.com"})
        response = self.client.post(self.FORGOT, {"email": "maya@example.com"})
        self.assertContains(response, "Too many reset emails from here.")
        self.assertEqual(len(mail.outbox), 5)


class SendTestEmailCommandTests(TestCase):
    def test_with_email_off(self):
        with self.assertRaisesMessage(CommandError, "Email is off."):
            call_command("send_test_email", "dana@example.com")

    @override_settings(**ON)
    def test_sending_one(self):
        call_command("send_test_email", "dana@example.com", stdout=open("/dev/null", "w"))
        self.assertEqual(mail.outbox[0].to, ["dana@example.com"])
        self.assertIn("Sent from the server", mail.outbox[0].body)

    @override_settings(**ON)
    def test_when_it_fails(self):
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=socket.timeout("timed out")):
            with self.assertRaisesMessage(CommandError, "didn't go out"):
                call_command("send_test_email", "dana@example.com")
