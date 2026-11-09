import hashlib
import hmac
import json
import time
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role

from . import services, stripe_api
from .models import Donation, MonthlyDonation, StripeCustomer, StripeSetup, fee_for, money

User = get_user_model()
DONATE = reverse("donations:donate")
WEBHOOK = reverse("donations:webhook")
CONNECTED = {"STRIPE_SECRET_KEY": "sk_test_123", "STRIPE_WEBHOOK_SECRET": "whsec_env", "SITE_URL": "https://example.org",
             "DONATIONS_TAX_DEDUCTIBLE": True, "DONATIONS_TAX_ID": "12-3456789", "DONATION_SEND_RECEIPTS": True}


def checkout_session(donation, **extra):
    session = {
        "id": "cs_test_1", "object": "checkout.session", "mode": "payment", "status": "complete",
        "payment_status": "paid", "livemode": False, "customer": "cus_1", "payment_intent": "pi_1",
        "customer_details": {"name": "Maya Okafor", "email": "maya@example.com"},
        "metadata": {"donation": str(donation.pk), "token": str(donation.token)},
    }
    session.update(extra)
    return session


def make_admin(username="boss", **fields):
    """An account with the Admin role, which also makes it staff."""
    user = User.objects.create_user(username, f"{username}@example.com", "x", **fields)
    user.profile.roles.add(Role.objects.get(slug=Role.ADMIN))
    user.refresh_from_db()
    return user


def signed(payload, secret="whsec_env"):
    stamp = int(time.time())
    digest = hmac.new(secret.encode(), f"{stamp}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={stamp},v1={digest}"


class MoneyTests(TestCase):
    def test_money(self):
        self.assertEqual([money(c) for c in (5000, 3750, 123456, 5)], ["$50", "$37.50", "$1,234.56", "$0.05"])

    def test_the_fee_covers_stripes_cut(self):
        for cents in (500, 2500, 5000, 3750, 100000):
            total = cents + fee_for(cents)
            stripe_keeps = round(total * settings.DONATION_FEE_PERCENT / 100) + settings.DONATION_FEE_CENTS
            self.assertGreaterEqual(total - stripe_keeps, cents)
            self.assertLess(total - stripe_keeps - cents, 2)


@override_settings(**CONNECTED)
class DonatePageTests(TestCase):
    def setUp(self):
        cache.clear()
        sessions = ({"id": f"cs_test_{n}", "url": f"https://checkout.stripe.com/c/pay/cs_test_{n}", "livemode": False}
                    for n in range(1, 100))
        patcher = mock.patch.object(stripe_api, "create_checkout_session", side_effect=lambda **params: next(sessions))
        self.create = patcher.start()
        self.addCleanup(patcher.stop)

    def params(self):
        return self.create.call_args.kwargs

    def test_the_page_offers_every_choice(self):
        html = self.client.get(DONATE).content.decode()
        for text in ["One-time", "Monthly", "$10", "$25", "$50", "$100", "$250", "Other", "Donate $50",
                     "No account needed.", "Create an account", "501(c)(3)", "EIN: 12-3456789"]:
            self.assertIn(text, html)
        self.assertIn("/accounts/login/?next=", html)
        self.assertIn("/accounts/register/?next=", html)

    def test_a_one_time_donation_goes_to_stripe_checkout(self):
        response = self.client.post(DONATE, {"frequency": "once", "amount": "50"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], "https://checkout.stripe.com/c/pay/cs_test_1")
        donation = Donation.objects.get()
        self.assertEqual((donation.amount, donation.status, donation.frequency, donation.language),
                         (5000, Donation.PENDING, Donation.ONE_TIME, "en"))
        self.assertEqual(donation.stripe_checkout_session, "cs_test_1")
        params = self.params()
        self.assertEqual(params["mode"], "payment")
        self.assertEqual(params["submit_type"], "donate")
        self.assertEqual(params["line_items"][0]["price_data"]["unit_amount"], 5000)
        self.assertEqual(params["line_items"][0]["price_data"]["product_data"]["name"],
                         "Donation to Tahoe Neighborhood Table")
        self.assertNotIn("recurring", params["line_items"][0]["price_data"])
        self.assertEqual(params["locale"], "en")
        self.assertEqual(params["customer_creation"], "always")
        self.assertIn("501(c)(3)", params["custom_text"]["submit"]["message"])
        self.assertTrue(params["success_url"].endswith(f"/donate/receipt/{donation.token}/?session_id={{CHECKOUT_SESSION_ID}}"))
        self.assertIn("canceled=1", params["cancel_url"])

    def test_a_monthly_donation_in_spanish_with_the_fee_covered(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "es"
        self.client.post(DONATE, {"frequency": "monthly", "amount": "other", "other_amount": "$37.50", "cover_fee": "1"})
        donation = Donation.objects.get()
        self.assertEqual((donation.amount, donation.fee_covered, donation.language), (3893, 143, "es"))
        params = self.params()
        price = params["line_items"][0]["price_data"]
        self.assertEqual(params["mode"], "subscription")
        self.assertEqual(price["recurring"], {"interval": "month"})
        self.assertEqual(price["unit_amount"], 3893)
        self.assertEqual(price["product_data"]["name"], "Donación a Tahoe Neighborhood Table")
        self.assertEqual(params["locale"], "es-419")
        self.assertNotIn("customer_creation", params)  # Stripe always makes a customer for monthly donations
        self.assertIn("cover_fee=1", params["cancel_url"])

    def test_signed_in_donors_are_linked_to_their_account(self):
        user = User.objects.create_user("maya", "maya@example.com", "x", first_name="Maya", last_name="Okafor")
        self.client.force_login(user)
        self.client.post(DONATE, {"frequency": "once", "amount": "25"})
        self.assertEqual(self.params()["customer_email"], "maya@example.com")
        self.assertEqual(Donation.objects.get().user, user)
        StripeCustomer.objects.create(user=user, customer="cus_maya", livemode=False)
        self.client.post(DONATE, {"frequency": "once", "amount": "25"})
        self.assertEqual(self.params()["customer"], "cus_maya")
        self.assertNotIn("customer_email", self.params())

    def test_amounts_are_checked(self):
        cases = [({"amount": "other", "other_amount": "abc"}, "Enter an amount in dollars"),
                 ({"amount": "other", "other_amount": "2"}, "The smallest donation we can take online is $5."),
                 ({"amount": "other", "other_amount": "20000"}, "please email us"),
                 ({"amount": "other", "other_amount": "12.345"}, "Enter an amount in dollars"),
                 ({"amount": "other", "other_amount": ""}, "Enter an amount."),
                 ({"amount": "7"}, "Choose an amount.")]
        for data, message in cases:
            response = self.client.post(DONATE, {"frequency": "once", **data})
            self.assertContains(response, message, msg_prefix=str(data))
        self.client.post(DONATE, {"frequency": "once", "amount": "50", "website": "spam"})  # a bot
        self.assertFalse(Donation.objects.exists())
        self.create.assert_not_called()

    def test_when_stripe_cant_be_reached(self):
        self.create.side_effect = stripe_api.StripeError("down")
        response = self.client.post(DONATE, {"frequency": "once", "amount": "50"})
        self.assertContains(response, "nothing was charged")
        self.assertEqual(Donation.objects.get().status, Donation.FAILED)

    def test_coming_back_from_stripe_keeps_the_choices(self):
        html = self.client.get(DONATE + "?canceled=1&frequency=monthly&amount=37.50&cover_fee=1").content.decode()
        self.assertIn("you weren’t charged", html)
        self.assertIn('name="frequency" value="monthly" checked', html)
        self.assertIn('name="amount" value="other" checked', html)
        self.assertIn('value="37.50"', html)
        self.assertIn('name="cover_fee" value="1" checked', html)
        self.assertIn("Donate $38.93 a month", html)


class NotConnectedTests(TestCase):
    """Before Stripe is connected, the Donate buttons open an email, and admins see a preview."""

    def test_visitors_get_an_email_link(self):
        home = self.client.get("/").content.decode()
        self.assertIn('class="act act--give" href="mailto:info@tahoeneighborhoodtable.com?subject=Donating%20to', home)
        self.assertContains(self.client.get(DONATE), "Online donations are coming soon")

    @mock.patch.object(stripe_api, "create_checkout_session")
    def test_admins_preview_the_whole_donation(self, create):
        self.client.force_login(make_admin(first_name="Ana", last_name="Ruiz"))
        self.assertIn('href="/donate/"', self.client.get("/").content.decode())
        self.assertContains(self.client.get(DONATE), "Admin preview.")
        response = self.client.post(DONATE, {"frequency": "monthly", "amount": "25"})
        self.assertContains(response, "Thank you, Ana!")
        self.assertContains(response, "TNT-PREVIEW")
        self.assertContains(response, "Your monthly donation of $25 is set up.")
        self.assertFalse(Donation.objects.exists())
        create.assert_not_called()


@override_settings(**CONNECTED)
class ReceiptTests(TestCase):
    def setUp(self):
        self.donation = Donation.objects.create(amount=5143, fee_covered=143, stripe_checkout_session="cs_test_1")
        self.url = reverse("donations:receipt", args=[self.donation.token])

    @mock.patch.object(stripe_api, "retrieve_checkout_session")
    def test_the_thank_you_page_confirms_with_stripe(self, retrieve):
        retrieve.return_value = checkout_session(self.donation)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(self.url + "?session_id=cs_test_1")
        retrieve.assert_called_once_with("cs_test_1")
        for text in ["Thank you, Maya!", "Your donation of $51.43 to Tahoe Neighborhood Table is complete.",
                     self.donation.number, "maya@example.com", "Includes $1.43 you added to cover the card fee",
                     "No goods or services were provided", "EIN: 12-3456789"]:
            self.assertContains(response, text)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, Donation.PAID)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["maya@example.com"])
        self.assertIn("Thank you for your donation of $51.43", mail.outbox[0].body)
        self.assertIn(f"https://example.org{self.url}", mail.outbox[0].body)

    @mock.patch.object(stripe_api, "retrieve_checkout_session")
    def test_someone_elses_session_isnt_checked(self, retrieve):
        response = self.client.get(self.url + "?session_id=cs_test_other")
        retrieve.assert_not_called()
        self.assertContains(response, "still being processed")

    def test_a_spanish_receipt(self):
        Donation.objects.filter(pk=self.donation.pk).update(status=Donation.PAID, paid_at=timezone.now(),
                                                            name="Ana Ruiz", language="es")
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "es"
        response = self.client.get(self.url)
        self.assertContains(response, "Recibo de donación")
        self.assertContains(response, "deducibles de impuestos")


@override_settings(**CONNECTED)
class WebhookTests(TestCase):
    def setUp(self):
        self.donation = Donation.objects.create(amount=2500, stripe_checkout_session="cs_test_1")

    def send(self, kind, obj, secret="whsec_env"):
        payload = json.dumps({"id": "evt_1", "type": kind, "data": {"object": obj}})
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(WEBHOOK, payload, content_type="application/json",
                                    headers={"stripe-signature": signed(payload, secret)})

    def test_unsigned_messages_are_turned_away(self):
        payload = json.dumps({"type": "checkout.session.completed", "data": {"object": {}}})
        self.assertEqual(self.client.post(WEBHOOK, payload, content_type="application/json").status_code, 400)
        response = self.client.post(WEBHOOK, payload, content_type="application/json",
                                    headers={"stripe-signature": signed(payload, "whsec_wrong")})
        self.assertEqual(response.status_code, 400)

    def test_a_paid_checkout_is_recorded_once(self):
        session = checkout_session(self.donation)
        self.assertEqual(self.send("checkout.session.completed", session).status_code, 200)
        self.assertEqual(self.send("checkout.session.completed", session).status_code, 200)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, Donation.PAID)
        self.assertEqual((self.donation.name, self.donation.stripe_payment_intent), ("Maya Okafor", "pi_1"))
        self.assertEqual(len(mail.outbox), 1)

    def test_the_secret_saved_by_connect_stripe_works_too(self):
        StripeSetup.objects.create(livemode=False, site_url="https://example.org", webhook_secret="whsec_saved")
        response = self.send("checkout.session.completed", checkout_session(self.donation), secret="whsec_saved")
        self.assertEqual(response.status_code, 200)

    def test_a_monthly_donation_month_by_month(self):
        user = User.objects.create_user("maya", "maya@example.com", "x")
        Donation.objects.filter(pk=self.donation.pk).update(frequency=Donation.MONTHLY, user=user)
        session = checkout_session(self.donation, mode="subscription", payment_intent=None, subscription="sub_1",
                                   invoice="in_1")
        self.send("checkout.session.completed", session)
        monthly = MonthlyDonation.objects.get()
        self.assertEqual((monthly.stripe_subscription, monthly.amount, monthly.user), ("sub_1", 2500, user))
        self.assertEqual(StripeCustomer.objects.get(user=user).customer, "cus_1")
        # The first month's invoice was paid in Checkout, so it doesn't count twice.
        first_invoice = {"id": "in_1", "billing_reason": "subscription_create", "amount_paid": 2500, "livemode": False,
                         "parent": {"subscription_details": {"subscription": "sub_1"}}}
        self.send("invoice.paid", first_invoice)
        self.assertEqual(Donation.objects.count(), 1)
        # Each later month is a new donation with its own receipt.
        next_invoice = {**first_invoice, "id": "in_2", "billing_reason": "subscription_cycle", "customer": "cus_1",
                        "customer_email": "maya@example.com"}
        self.send("invoice.paid", next_invoice)
        self.send("invoice.paid", next_invoice)
        second = Donation.objects.get(stripe_invoice="in_2")
        self.assertEqual((second.status, second.amount, second.monthly, second.user),
                         (Donation.PAID, 2500, monthly, user))
        self.assertEqual(Donation.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 2)
        # The donor asks to stop after this month, then the subscription ends.
        ends = int(time.time()) + 86400 * 20
        self.send("customer.subscription.updated", {"id": "sub_1", "status": "active", "cancel_at": ends})
        monthly.refresh_from_db()
        self.assertEqual(int(monthly.ends_at.timestamp()), ends)
        self.send("customer.subscription.deleted", {"id": "sub_1", "status": "canceled", "canceled_at": ends})
        monthly.refresh_from_db()
        self.assertEqual(monthly.status, "canceled")
        self.assertIsNotNone(monthly.canceled_at)

    def test_refunds_failures_and_abandoned_checkouts(self):
        self.send("checkout.session.completed", checkout_session(self.donation))
        self.send("charge.refunded", {"id": "ch_1", "payment_intent": "pi_1", "refunded": True, "amount_refunded": 2500})
        self.donation.refresh_from_db()
        self.assertEqual((self.donation.status, self.donation.amount_refunded), (Donation.REFUNDED, 2500))
        bank = Donation.objects.create(amount=5000, stripe_checkout_session="cs_test_2")
        self.send("checkout.session.async_payment_failed", checkout_session(bank, id="cs_test_2", payment_status="unpaid"))
        self.assertEqual(Donation.objects.get(pk=bank.pk).status, Donation.FAILED)
        left = Donation.objects.create(amount=5000, stripe_checkout_session="cs_test_3")
        self.send("checkout.session.expired", checkout_session(left, id="cs_test_3", status="expired",
                                                                payment_status="unpaid"))
        self.assertEqual(Donation.objects.get(pk=left.pk).status, Donation.EXPIRED)

    def test_a_problem_asks_stripe_to_try_again(self):
        with mock.patch.object(services, "handle_event", side_effect=RuntimeError("bug")):
            response = self.send("checkout.session.completed", checkout_session(self.donation))
        self.assertEqual(response.status_code, 500)


@override_settings(**CONNECTED)
class MonthlyManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("maya", "maya@example.com", "x", first_name="Maya")
        self.client.force_login(self.user)

    @mock.patch.object(stripe_api, "create_portal_session",
                       return_value={"url": "https://billing.stripe.com/p/session/test_1"})
    def test_donors_manage_their_monthly_donation_on_stripe(self, portal):
        StripeCustomer.objects.create(user=self.user, customer="cus_1", livemode=False)
        MonthlyDonation.objects.create(stripe_subscription="sub_1", user=self.user, amount=2500)
        StripeSetup.objects.create(livemode=False, site_url="https://example.org", portal_configuration="bpc_1")
        dashboard = self.client.get(reverse("accounts:user_dashboard"))
        self.assertContains(dashboard, "$25 a month")
        self.assertContains(dashboard, "Change or stop monthly donation")
        response = self.client.post(reverse("donations:manage"))
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], "https://billing.stripe.com/p/session/test_1")
        self.assertEqual(portal.call_args.args[0], "cus_1")
        self.assertEqual(portal.call_args.args[2], "bpc_1")

    def test_without_a_monthly_donation(self):
        response = self.client.post(reverse("donations:manage"), follow=True)
        self.assertContains(response, "no monthly donation to change")

    def test_the_dashboard_lists_receipts(self):
        paid = Donation.objects.create(user=self.user, amount=5000, status=Donation.PAID, paid_at=timezone.now())
        Donation.objects.create(user=self.user, amount=9900, status=Donation.EXPIRED)
        html = self.client.get(reverse("accounts:user_dashboard")).content.decode()
        self.assertIn("$50", html)
        self.assertNotIn("$99", html)
        self.assertIn(reverse("donations:receipt", args=[paid.token]), html)


@override_settings(**CONNECTED)
class AdminTests(TestCase):
    def setUp(self):
        self.client.force_login(make_admin(is_superuser=True))

    def test_the_dashboard_totals_this_years_donations(self):
        now = timezone.now()
        Donation.objects.create(amount=5000, status=Donation.PAID, paid_at=now, email="a@example.com")
        Donation.objects.create(amount=2500, status=Donation.PAID, paid_at=now, email="b@example.com")
        Donation.objects.create(amount=9900, status=Donation.PENDING)
        MonthlyDonation.objects.create(stripe_subscription="sub_1", amount=2500)
        html = self.client.get(reverse("accounts:admin_dashboard")).content.decode()
        self.assertIn("$75", html)
        self.assertIn("from 2 donations", html)
        self.assertIn("$25 a month", html)
        self.assertIn("Test mode", html)

    def test_the_donation_list_and_download(self):
        donation = Donation.objects.create(amount=5000, status=Donation.PAID, paid_at=timezone.now(), name="=Maya",
                                           email="maya@example.com")
        url = reverse("admin:donations_donation_changelist")
        self.assertContains(self.client.get(url), donation.number)
        self.assertContains(self.client.get(url + "?q=maya@example.com"), donation.number)
        response = self.client.post(url, {"action": "download_csv", "_selected_action": [donation.pk]})
        text = response.content.decode("utf-8-sig")
        self.assertIn("Receipt,Date paid,Name", text.splitlines()[0])
        self.assertIn("'=Maya", text)
        self.assertIn(donation.number, text)


class ConnectStripeTests(TestCase):
    @override_settings(STRIPE_SECRET_KEY="")
    def test_needs_a_key(self):
        with self.assertRaises(CommandError):
            call_command("connect_stripe")

    @override_settings(STRIPE_SECRET_KEY="sk_test_123", SITE_URL="https://example.org")
    def test_sets_up_stripe_once(self):
        endpoint_url = "https://example.org/donate/stripe/webhook/"
        calls = {
            "list_webhook_endpoints": mock.Mock(return_value=[]),
            "create_webhook_endpoint": mock.Mock(return_value={"id": "we_1", "secret": "whsec_1"}),
            "update_webhook_endpoint": mock.Mock(return_value={}),
            "create_product": mock.Mock(side_effect=[{"id": "prod_en"}, {"id": "prod_es"}]),
            "update_product": mock.Mock(return_value={}),
            "create_portal_configuration": mock.Mock(return_value={
                "id": "bpc_1", "login_page": {"url": "https://billing.stripe.com/p/login/test_1"}}),
        }
        with mock.patch.multiple(stripe_api, **calls):
            call_command("connect_stripe", stdout=mock.MagicMock())
            setup = StripeSetup.objects.get(livemode=False)
            self.assertEqual((setup.webhook_endpoint, setup.webhook_secret), ("we_1", "whsec_1"))
            self.assertEqual(setup.products, {"en": "prod_en", "es": "prod_es"})
            self.assertEqual(setup.portal_login_url, "https://billing.stripe.com/p/login/test_1")
            created = calls["create_webhook_endpoint"].call_args.kwargs
            self.assertEqual(created["url"], endpoint_url)
            self.assertEqual(created["enabled_events"], stripe_api.WEBHOOK_EVENTS)
            spanish = calls["create_product"].call_args_list[1].kwargs
            self.assertEqual(spanish["name"], "Donación a Tahoe Neighborhood Table")

            # Running it again updates what's there instead of adding more.
            calls["list_webhook_endpoints"].return_value = [{"id": "we_1", "url": endpoint_url}]
            call_command("connect_stripe", stdout=mock.MagicMock())
            self.assertEqual(calls["create_webhook_endpoint"].call_count, 1)
            self.assertEqual(calls["create_product"].call_count, 2)
            self.assertEqual(calls["update_product"].call_count, 2)
            self.assertEqual(calls["create_portal_configuration"].call_count, 1)
            calls["update_webhook_endpoint"].assert_called_once()

        # Donations now use the saved product, in the donor's language.
        donation = Donation.objects.create(amount=5000, language="es")
        request = mock.Mock(build_absolute_uri=lambda path: "https://example.org" + path)
        price = services.checkout_params(donation, request)["line_items"][0]["price_data"]
        self.assertEqual(price["product"], "prod_es")
