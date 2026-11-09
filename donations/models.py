"""Donations made through Stripe, and the monthly donations behind repeat payments."""

import math
import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

PRESETS = [10, 25, 50, 100, 250]  # suggested amounts, in dollars
MIN_CENTS = 500
MAX_CENTS = 1_000_000


def money(cents):
    """$50, or $52.08 when there are cents. Always US style, since every donation is in US dollars."""
    dollars, rest = divmod(int(cents), 100)
    return f"${dollars:,}" if not rest else f"${dollars:,}.{rest:02d}"


def dollars(cents):
    """The amount as typed in a form: 50, or 37.50."""
    whole, rest = divmod(int(cents), 100)
    return f"{whole}" if not rest else f"{whole}.{rest:02d}"


def fee_for(cents):
    """What to add to a donation so that, after Stripe's card fee, the full amount reaches us."""
    rate = settings.DONATION_FEE_PERCENT / 100
    total = math.ceil((cents + settings.DONATION_FEE_CENTS) / (1 - rate))
    return total - cents


def stripe_mode():
    """'live' with a live key, 'test' with a test key, and '' when Stripe isn't connected."""
    key = settings.STRIPE_SECRET_KEY
    if not key:
        return ""
    return "live" if key.startswith(("sk_live_", "rk_live_")) else "test"


def default_language():
    return settings.LANGUAGE_CODE


class MonthlyDonation(models.Model):
    """A donation that repeats every month: a Stripe subscription."""

    STATUSES = [
        ("active", _("Active")),
        ("past_due", _("Payment overdue")),
        ("unpaid", _("Unpaid")),
        ("incomplete", _("Not started")),
        ("incomplete_expired", _("Not started")),
        ("paused", _("Paused")),
        ("canceled", _("Canceled")),
    ]

    stripe_subscription = models.CharField(_("Stripe subscription"), max_length=255, unique=True)
    stripe_customer = models.CharField(_("Stripe customer"), max_length=255, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="monthly_donations", verbose_name=_("account"))
    name = models.CharField(_("name"), max_length=200, blank=True)
    email = models.EmailField(_("email"), blank=True)
    amount = models.PositiveIntegerField(_("amount each month, in cents"))
    fee_covered = models.PositiveIntegerField(_("fee covered each month, in cents"), default=0)
    status = models.CharField(_("status"), max_length=24, choices=STATUSES, default="active")
    ends_at = models.DateTimeField(_("ends"), null=True, blank=True,
                                   help_text=_("Set when the donor has asked to stop after the current month."))
    language = models.CharField(_("language"), max_length=8, choices=settings.LANGUAGES, default=default_language)
    livemode = models.BooleanField(_("real payments"), default=False,
                                   help_text=_("Unticked for test payments made with a Stripe test key."))
    started_at = models.DateTimeField(_("started"), auto_now_add=True)
    canceled_at = models.DateTimeField(_("stopped"), null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = _("monthly donation")
        verbose_name_plural = _("monthly donations")

    def __str__(self):
        return _("%(amount)s a month from %(donor)s") % {"amount": money(self.amount), "donor": self.donor}

    @property
    def donor(self):
        return self.name or self.email or _("a donor")

    @property
    def amount_text(self):
        return money(self.amount)

    @property
    def is_active(self):
        return self.status in ("active", "past_due")


class Donation(models.Model):
    """One payment: a one-time donation, or one month of a monthly donation."""

    ONE_TIME = "once"
    MONTHLY = "monthly"
    FREQUENCIES = [(ONE_TIME, _("One-time")), (MONTHLY, _("Monthly"))]

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    STATUSES = [
        (PENDING, _("Not paid yet")),
        (PAID, _("Paid")),
        (FAILED, _("Payment failed")),
        (EXPIRED, _("Not completed")),
        (REFUNDED, _("Refunded")),
    ]

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="donations", verbose_name=_("account"))
    monthly = models.ForeignKey(MonthlyDonation, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="payments", verbose_name=_("monthly donation"))
    frequency = models.CharField(_("frequency"), max_length=8, choices=FREQUENCIES, default=ONE_TIME)
    amount = models.PositiveIntegerField(_("amount, in cents"), help_text=_("What the donor paid, fee included."))
    fee_covered = models.PositiveIntegerField(_("fee covered, in cents"), default=0,
                                              help_text=_("The part of the amount the donor added for the card fee."))
    amount_refunded = models.PositiveIntegerField(_("refunded, in cents"), default=0)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=PENDING)
    name = models.CharField(_("name"), max_length=200, blank=True)
    email = models.EmailField(_("email"), blank=True)
    language = models.CharField(_("language"), max_length=8, choices=settings.LANGUAGES, default=default_language)
    livemode = models.BooleanField(_("real payment"), default=False,
                                   help_text=_("Unticked for test payments made with a Stripe test key."))
    stripe_checkout_session = models.CharField(_("Stripe Checkout session"), max_length=255, null=True,
                                               blank=True, unique=True)
    stripe_invoice = models.CharField(_("Stripe invoice"), max_length=255, null=True, blank=True, unique=True)
    stripe_payment_intent = models.CharField(_("Stripe payment"), max_length=255, blank=True)
    stripe_customer = models.CharField(_("Stripe customer"), max_length=255, blank=True)
    receipt_sent_at = models.DateTimeField(_("receipt emailed"), null=True, blank=True)
    created_at = models.DateTimeField(_("started"), auto_now_add=True)
    paid_at = models.DateTimeField(_("date paid"), null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("donation")
        verbose_name_plural = _("donations")

    def __str__(self):
        return _("%(amount)s from %(donor)s") % {"amount": money(self.amount), "donor": self.donor}

    @property
    def number(self):
        """The receipt number, like TNT-00042."""
        return f"TNT-{self.pk:05d}" if self.pk else "TNT-PREVIEW"

    @property
    def donor(self):
        return self.name or self.email or _("a donor")

    @property
    def amount_text(self):
        return money(self.amount)

    @property
    def fee_text(self):
        return money(self.fee_covered)

    @property
    def refunded_text(self):
        return money(self.amount_refunded)

    @property
    def is_paid(self):
        return self.status == self.PAID

    @property
    def is_monthly(self):
        return self.frequency == self.MONTHLY


class StripeCustomer(models.Model):
    """The Stripe customer that goes with an account, so its donations and receipts stay together."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stripe_customers")
    customer = models.CharField(max_length=255)
    livemode = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "livemode"], name="one_stripe_customer_per_mode")]
        verbose_name = _("Stripe customer")
        verbose_name_plural = _("Stripe customers")

    def __str__(self):
        return self.customer


class StripeSetup(models.Model):
    """What `manage.py connect_stripe` set up in Stripe, once for test payments and once for real ones."""

    livemode = models.BooleanField(unique=True)
    site_url = models.URLField()
    webhook_endpoint = models.CharField(max_length=255, blank=True)
    webhook_secret = models.CharField(max_length=255, blank=True)
    portal_configuration = models.CharField(max_length=255, blank=True)
    portal_login_url = models.URLField(blank=True)
    products = models.JSONField(default=dict, blank=True)  # the Donation product in each language
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Stripe setup")
        verbose_name_plural = _("Stripe setup")

    def __str__(self):
        return _("Real payments") if self.livemode else _("Test payments")

    @classmethod
    def current(cls):
        mode = stripe_mode()
        if not mode:
            return None
        return cls.objects.filter(livemode=(mode == "live")).first()
