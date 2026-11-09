import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from pages.languages import current_language
from pages.limits import over_limit

from . import services, stripe_api
from .forms import DonateForm
from .models import (MAX_CENTS, MIN_CENTS, PRESETS, Donation, MonthlyDonation, StripeCustomer, StripeSetup,
                     fee_for, money, stripe_mode)

log = logging.getLogger(__name__)


def _return_link(view, form_data):
    """The Log in and Create an account links, which bring the donor back with their choices kept."""
    keep = {key: form_data.get(key) for key in ("frequency", "amount", "cover_fee") if form_data.get(key)}
    if keep.get("amount") == "other":
        keep["amount"] = form_data.get("other_amount") or ""
    target = reverse("donations:donate") + ("?" + urlencode(keep) if keep else "")
    return reverse(view) + "?" + urlencode({"next": target})


def _chosen_cents(chosen):
    """The amount picked so far, in cents, or None if there isn't a usable one yet."""
    if chosen["amount"] == "other":
        try:
            value = Decimal(chosen["other_amount"].replace("$", "").replace(",", "").strip())
        except InvalidOperation:
            return None
        cents = int(value * 100) if value.is_finite() else None
    elif chosen["amount"].isdigit():
        cents = int(chosen["amount"]) * 100
    else:
        return None
    return cents if cents is not None and MIN_CENTS <= cents <= MAX_CENTS else None


def _page(request, form, preview, **extra):
    data = form.data if form.is_bound else {k: v for k, v in form.initial.items() if v not in (None, False)}
    chosen = {
        "frequency": data.get("frequency") or Donation.ONE_TIME,
        "amount": data.get("amount") or "",
        "other_amount": data.get("other_amount") or "",
        "cover_fee": data.get("cover_fee") in (True, "1", "on", "true"),
    }
    cents = _chosen_cents(chosen)
    if cents:
        fee = fee_for(cents)
        fee_text = gettext("Add %(fee)s to cover the card fee, so your whole donation reaches our neighbors.") % {
            "fee": money(fee)}
        submit_label = services.amount_label(cents + (fee if chosen["cover_fee"] else 0),
                                             chosen["frequency"] == Donation.MONTHLY)
    else:
        fee_text = gettext("Add a little to cover the card fee, so your whole donation reaches our neighbors.")
        submit_label = gettext("Donate")
    context = {
        "form": form,
        "preview": preview,
        "presets": [(str(p), money(p * 100)) for p in PRESETS],
        "frequencies": Donation.FREQUENCIES,
        "chosen": chosen,
        "fee_text": fee_text,
        "submit_label": submit_label,
        "tax_note": services.tax_note(),
        "tax_id": settings.DONATIONS_TAX_ID if settings.DONATIONS_TAX_DEDUCTIBLE else "",
        "fee_percent": settings.DONATION_FEE_PERCENT,
        "fee_cents": settings.DONATION_FEE_CENTS,
        "login_link": _return_link("accounts:login", data),
        "register_link": _return_link("accounts:register", data),
        "canceled": request.GET.get("canceled") == "1",
        **extra,
    }
    return render(request, "donations/donate.html", context)


@never_cache
@require_http_methods(["GET", "POST"])
def donate(request):
    """The donation form. Sending it opens Stripe Checkout, where the donor pays."""
    live = bool(stripe_mode())
    preview = not live and request.user.is_authenticated and request.user.is_staff
    if not live and not preview:
        return render(request, "donations/unavailable.html")

    if request.method == "GET":
        return _page(request, DonateForm(initial=DonateForm.initial_from(request.GET)), preview)

    form = DonateForm(request.POST)
    if not form.is_valid():
        return _page(request, form, preview)
    if over_limit(request, "donate", limit=20, seconds=600):
        return _page(request, form, preview, problem=gettext("Too many tries. Wait a few minutes, then try again."))

    data = form.cleaned_data
    user = request.user if request.user.is_authenticated else None
    donation = Donation(
        user=user,
        frequency=data["frequency"],
        amount=data["cents"] + data["fee"],
        fee_covered=data["fee"],
        name=user.get_full_name() if user else "",
        email=user.email if user else "",
        language=current_language(),
    )
    if preview:
        # Nothing is saved or charged: the admin sees the receipt a donor would get.
        donation.status = Donation.PAID
        donation.paid_at = timezone.now()
        donation.name = donation.name or gettext("Sample Donor")
        donation.email = donation.email or "donor@example.com"
        return _receipt_page(request, donation, thanks=True, preview=True)

    donation.save()
    try:
        url = services.start_checkout(donation, request)
    except stripe_api.StripeError:
        log.exception("Couldn't start Stripe Checkout for donation %s", donation.pk)
        donation.status = Donation.FAILED
        donation.save(update_fields=["status"])
        return _page(request, form, preview, problem=gettext(
            "We couldn’t reach our payment service, so nothing was charged. Please try again in a minute."))
    return HttpResponseRedirect(url, status=303)


def _receipt_page(request, donation, thanks, preview=False):
    setup = None if preview else StripeSetup.current()
    monthly = donation.monthly
    owner = request.user.is_authenticated and donation.user_id == request.user.pk
    context = {
        "donation": donation,
        "monthly": monthly,
        "thanks": thanks,
        "preview": preview,
        "tax_statement": services.tax_statement(),
        "can_manage": bool(owner and monthly and monthly.is_active),
        "portal_login_url": setup.portal_login_url if setup and monthly and monthly.is_active and not owner else "",
        "first_name": (donation.name or "").split(" ")[0],
    }
    return render(request, "donations/receipt.html", context)


@never_cache
def receipt(request, token):
    """The thank-you page after paying, and the donation's receipt from then on."""
    donation = get_object_or_404(Donation.objects.select_related("monthly"), token=token)
    session_id = request.GET.get("session_id", "")
    if session_id and session_id == donation.stripe_checkout_session and donation.status == Donation.PENDING:
        # Usually Stripe's webhook has already told us; if not, ask Stripe now.
        try:
            donation = services.record_checkout(stripe_api.retrieve_checkout_session(session_id)) or donation
        except stripe_api.StripeError:
            log.warning("Couldn't check Checkout session %s; waiting for the webhook.", session_id)
    return _receipt_page(request, donation, thanks=bool(session_id))


@login_required
@require_POST
def manage(request):
    """Opens Stripe's page where a signed-in donor changes or stops their monthly donation."""
    livemode = stripe_mode() == "live"
    customer = StripeCustomer.objects.filter(user=request.user, livemode=livemode).first()
    has_monthly = MonthlyDonation.objects.filter(user=request.user, livemode=livemode).exists()
    if not (stripe_mode() and customer and has_monthly):
        messages.error(request, gettext("There’s no monthly donation to change on this account."))
        return redirect("accounts:user_dashboard")
    setup = StripeSetup.current()
    try:
        portal = stripe_api.create_portal_session(
            customer.customer, request.build_absolute_uri(reverse("accounts:user_dashboard")),
            setup.portal_configuration if setup else "")
    except stripe_api.StripeError:
        log.exception("Couldn't open the Stripe customer portal for user %s", request.user.pk)
        messages.error(request, gettext("We couldn’t open that page just now. Please try again in a minute."))
        return redirect("accounts:user_dashboard")
    return HttpResponseRedirect(portal["url"], status=303)


@csrf_exempt
@require_POST
def webhook(request):
    """Stripe tells the site about payments here. Each message is signed, and unsigned ones are turned away."""
    secrets = [settings.STRIPE_WEBHOOK_SECRET, *StripeSetup.objects.values_list("webhook_secret", flat=True)]
    event = stripe_api.verify_event(request.body, request.headers.get("Stripe-Signature"), secrets)
    if event is None:
        return HttpResponse("Signature didn't match.", status=400, content_type="text/plain")
    try:
        services.handle_event(event)
    except Exception:
        log.exception("Couldn't handle Stripe event %s (%s)", event.get("id"), event.get("type"))
        return HttpResponse("Couldn't handle the event.", status=500, content_type="text/plain")
    return HttpResponse("OK", content_type="text/plain")
