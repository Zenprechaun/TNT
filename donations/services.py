"""Starting a donation in Stripe Checkout, and recording what Stripe reports back about it."""

import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.http import urlencode
from django.utils.translation import gettext

from emails.models import Email, EmailSettings
from emails.sending import send

from . import stripe_api
from .models import Donation, MonthlyDonation, StripeCustomer, StripeSetup, dollars, money, stripe_mode

log = logging.getLogger(__name__)

# The language Stripe Checkout uses for each of the site's languages. es-419 is Latin American Spanish.
CHECKOUT_LOCALES = {"en": "en", "es": "es-419"}


def donation_name():
    return gettext("Donation to Tahoe Neighborhood Table")


def tax_note():
    """The short line on the Donate page and in Stripe Checkout. Empty if donations aren't tax-deductible."""
    if not settings.DONATIONS_TAX_DEDUCTIBLE:
        return ""
    return gettext("Tahoe Neighborhood Table is a 501(c)(3) nonprofit. "
                   "Donations are tax-deductible to the extent allowed by law.")


def tax_statement():
    """The full statement on receipts, as donors need it for their taxes."""
    if not settings.DONATIONS_TAX_DEDUCTIBLE:
        return ""
    text = gettext("Tahoe Neighborhood Table is a tax-exempt organization under Section 501(c)(3) of the Internal "
                   "Revenue Code. Donations are tax-deductible to the extent allowed by law. No goods or services "
                   "were provided in exchange for this donation.")
    if settings.DONATIONS_TAX_ID:
        text += " " + gettext("EIN: %(ein)s") % {"ein": settings.DONATIONS_TAX_ID}
    return text


def site_url(path):
    return settings.SITE_URL.rstrip("/") + path


def _id(value):
    """Stripe sends some fields either as an ID or as the whole object."""
    if isinstance(value, dict):
        return value.get("id") or ""
    return value or ""


def _when(timestamp):
    return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc) if timestamp else None


def checkout_params(donation, request):
    """What to ask Stripe Checkout for: the amount, how often, the donor's language, and where to come back to."""
    monthly = donation.is_monthly
    livemode = stripe_mode() == "live"
    with translation.override(donation.language):
        name, note = donation_name(), tax_note()
    price = {"currency": "usd", "unit_amount": donation.amount}
    setup = StripeSetup.current()
    product = (setup.products or {}).get(donation.language) if setup else None
    if product:
        price["product"] = product
    else:
        price["product_data"] = {"name": name, **({"description": note} if note else {})}
    if monthly:
        price["recurring"] = {"interval": "month"}

    receipt = request.build_absolute_uri(reverse("donations:receipt", args=[donation.token]))
    again = {"canceled": "1", "frequency": donation.frequency, "amount": dollars(donation.amount - donation.fee_covered)}
    if donation.fee_covered:
        again["cover_fee"] = "1"
    metadata = {"donation": str(donation.pk), "token": str(donation.token)}
    params = {
        "mode": "subscription" if monthly else "payment",
        "line_items": [{"price_data": price, "quantity": 1}],
        "submit_type": "donate",
        "locale": CHECKOUT_LOCALES.get(donation.language, "auto"),
        "success_url": receipt + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": request.build_absolute_uri(reverse("donations:donate")) + "?" + urlencode(again),
        "client_reference_id": str(donation.pk),
        "metadata": metadata,
        "name_collection": {"individual": {"enabled": True}},
    }
    if note:
        params["custom_text"] = {"submit": {"message": note}}
    if monthly:
        params["subscription_data"] = {"description": name, "metadata": metadata}
    else:
        params["payment_intent_data"] = {"description": name, "metadata": metadata}

    customer = None
    if donation.user_id:
        known = StripeCustomer.objects.filter(user_id=donation.user_id, livemode=livemode).first()
        customer = known.customer if known else None
    if customer:
        params["customer"] = customer
    else:
        if donation.email:
            params["customer_email"] = donation.email
        if not monthly:
            params["customer_creation"] = "always"  # so receipts and any later questions tie to one donor
    return params


def start_checkout(donation, request):
    """Opens a Stripe Checkout for the donation and returns the page to send the donor to."""
    session = stripe_api.create_checkout_session(**checkout_params(donation, request))
    donation.stripe_checkout_session = session["id"]
    donation.livemode = bool(session.get("livemode"))
    donation.save(update_fields=["stripe_checkout_session", "livemode"])
    return session["url"]


def _mark_paid(donation):
    """Returns True if this changed the donation to paid."""
    if donation.status in (Donation.PENDING, Donation.FAILED, Donation.EXPIRED):
        donation.status = Donation.PAID
        donation.paid_at = timezone.now()
        return True
    return False


def _monthly_for(session, donation):
    subscription = _id(session.get("subscription"))
    monthly, _ = MonthlyDonation.objects.get_or_create(
        stripe_subscription=subscription,
        defaults={
            "stripe_customer": donation.stripe_customer,
            "user": donation.user,
            "name": donation.name,
            "email": donation.email,
            "amount": donation.amount,
            "fee_covered": donation.fee_covered,
            "language": donation.language,
            "livemode": donation.livemode,
        },
    )
    return monthly


def _donation_for_session(session):
    found = Donation.objects.select_for_update().filter(stripe_checkout_session=session["id"]).first()
    if found:
        return found
    metadata = session.get("metadata") or {}
    if metadata.get("donation") and metadata.get("token"):
        return (Donation.objects.select_for_update()
                .filter(pk=metadata["donation"], token=metadata["token"]).first())
    return None


@transaction.atomic
def record_checkout(session):
    """Records a finished (or expired) Stripe Checkout. Safe to run more than once for the same session."""
    donation = _donation_for_session(session)
    if donation is None:
        log.warning("Stripe reported Checkout session %s, which doesn't match a donation.", session.get("id"))
        return None
    details = session.get("customer_details") or {}
    donation.name = donation.name or details.get("name") or ""
    donation.email = donation.email or details.get("email") or ""
    donation.livemode = bool(session.get("livemode"))
    donation.stripe_checkout_session = session["id"]
    donation.stripe_customer = _id(session.get("customer")) or donation.stripe_customer
    if session.get("payment_intent"):
        donation.stripe_payment_intent = _id(session["payment_intent"])
    if session.get("invoice"):
        donation.stripe_invoice = _id(session["invoice"])
    if session.get("mode") == "subscription" and session.get("subscription"):
        donation.monthly = _monthly_for(session, donation)

    newly_paid = False
    if session.get("payment_status") in ("paid", "no_payment_required"):
        newly_paid = _mark_paid(donation)
    elif session.get("status") == "expired" and donation.status == Donation.PENDING:
        donation.status = Donation.EXPIRED
    donation.save()

    if donation.user_id and donation.stripe_customer:
        StripeCustomer.objects.update_or_create(
            user_id=donation.user_id, livemode=donation.livemode, defaults={"customer": donation.stripe_customer})
    if newly_paid:
        pk = donation.pk
        transaction.on_commit(lambda: send_receipt(pk))
    return donation


@transaction.atomic
def record_failed_checkout(session):
    donation = _donation_for_session(session)
    if donation and donation.status == Donation.PENDING:
        donation.status = Donation.FAILED
        donation.save(update_fields=["status"])


def _invoice_subscription(invoice):
    """The subscription behind an invoice, wherever this version of Stripe's API puts it."""
    if invoice.get("subscription"):
        return _id(invoice["subscription"])
    details = ((invoice.get("parent") or {}).get("subscription_details")) or {}
    return _id(details.get("subscription"))


@transaction.atomic
def record_invoice(invoice):
    """Records each month's payment of a monthly donation."""
    subscription = _invoice_subscription(invoice)
    if not subscription:
        return None
    if invoice.get("billing_reason") == "subscription_create":
        # The first month was paid in Checkout, and record_checkout records it.
        first = Donation.objects.select_for_update().filter(stripe_invoice=invoice["id"]).first()
        if first and _mark_paid(first):
            first.save()
            pk = first.pk
            transaction.on_commit(lambda: send_receipt(pk))
        return first
    monthly = MonthlyDonation.objects.filter(stripe_subscription=subscription).first()
    if monthly is None:
        log.warning("Stripe reported a payment for subscription %s, which isn't a monthly donation.", subscription)
        return None
    donation, created = Donation.objects.get_or_create(
        stripe_invoice=invoice["id"],
        defaults={
            "monthly": monthly,
            "user": monthly.user,
            "frequency": Donation.MONTHLY,
            "amount": invoice.get("amount_paid") or monthly.amount,
            "fee_covered": monthly.fee_covered,
            "name": invoice.get("customer_name") or monthly.name,
            "email": invoice.get("customer_email") or monthly.email,
            "language": monthly.language,
            "livemode": bool(invoice.get("livemode")),
            "stripe_customer": _id(invoice.get("customer")) or monthly.stripe_customer,
            "status": Donation.PAID,
            "paid_at": timezone.now(),
        },
    )
    if created:
        pk = donation.pk
        transaction.on_commit(lambda: send_receipt(pk))
    return donation


def record_subscription(subscription):
    """Keeps a monthly donation's status in step with Stripe: active, overdue, ending or stopped."""
    monthly = MonthlyDonation.objects.filter(stripe_subscription=subscription["id"]).first()
    if monthly is None:
        return None
    status = subscription.get("status") or monthly.status
    if status in dict(MonthlyDonation.STATUSES):
        monthly.status = status
    monthly.ends_at = _when(subscription.get("cancel_at"))
    if status == "canceled":
        monthly.canceled_at = _when(subscription.get("canceled_at")) or timezone.now()
        monthly.ends_at = None
    monthly.save()
    return monthly


def record_refund(charge):
    payment = _id(charge.get("payment_intent"))
    if not payment:
        return
    for donation in Donation.objects.filter(stripe_payment_intent=payment):
        donation.amount_refunded = charge.get("amount_refunded") or 0
        if charge.get("refunded"):
            donation.status = Donation.REFUNDED
        donation.save(update_fields=["amount_refunded", "status"])


def handle_event(event):
    """Acts on one webhook event from Stripe."""
    kind = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    if kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded", "checkout.session.expired"):
        record_checkout(obj)
    elif kind == "checkout.session.async_payment_failed":
        record_failed_checkout(obj)
    elif kind == "invoice.paid":
        record_invoice(obj)
    elif kind in ("customer.subscription.updated", "customer.subscription.deleted"):
        record_subscription(obj)
    elif kind == "charge.refunded":
        record_refund(obj)


def receipt_url(donation):
    return site_url(reverse("donations:receipt", args=[donation.token]))


def send_receipt(donation_pk):
    """Emails the donor a receipt, in the language they donated in. Only once, and only if the
    Management page has receipts turned on. The site keeps a copy (the emails app); if email is
    off or the email service is down, admins can send it from there later.
    """
    conf = EmailSettings.load()
    if not conf.donation_receipts:
        return
    donation = Donation.objects.filter(pk=donation_pk).first()
    if donation is None or donation.receipt_sent_at or not donation.email or not donation.is_paid:
        return
    try:
        with translation.override(donation.language):
            context = {"donation": donation, "receipt_url": receipt_url(donation), "tax": tax_statement(),
                       "site_email": settings.SITE_EMAIL}
            send(Email.RECEIPT, donation.email, gettext("Your donation receipt from Tahoe Neighborhood Table"),
                 render_to_string("donations/email/receipt.txt", context), ref=f"donation:{donation.pk}", conf=conf)
    except Exception:  # the donation is recorded either way
        log.exception("Couldn't prepare the receipt for donation %s", donation.pk)


def note_receipt_sent(sender, email, **kwargs):
    """When a receipt goes out, now or when an admin sends it again, the donation records it."""
    kind, _, pk = email.ref.partition(":")
    if email.kind == Email.RECEIPT and kind == "donation" and pk.isdigit():
        Donation.objects.filter(pk=int(pk), receipt_sent_at__isnull=True).update(receipt_sent_at=email.sent_at)


def amount_label(cents, monthly):
    """What the Donate button says: Donate $50, or Donate $25 a month."""
    if monthly:
        return gettext("Donate %(amount)s a month") % {"amount": money(cents)}
    return gettext("Donate %(amount)s") % {"amount": money(cents)}
