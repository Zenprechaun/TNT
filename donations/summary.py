"""Donations at a glance, for the Admin's Dashboard and the Management page."""

from django.db.models import Count, Sum
from django.utils import timezone

from .models import Donation, MonthlyDonation, StripeSetup, money, stripe_mode


def totals():
    """This year's donations and the monthly donors, for the kind of payments Stripe takes now (real or test)."""
    mode = stripe_mode()
    livemode = mode == "live"
    year = timezone.localdate().year
    paid = Donation.objects.filter(status=Donation.PAID, livemode=livemode, paid_at__year=year)
    sums = paid.aggregate(total=Sum("amount"), count=Count("pk"))
    monthly = MonthlyDonation.objects.filter(livemode=livemode, status__in=["active", "past_due"]).aggregate(
        count=Count("pk"), total=Sum("amount"))
    setup = StripeSetup.current()
    return {
        "connected": bool(mode),
        "mode": mode,
        "livemode": livemode,
        "updates_connected": bool(setup and setup.webhook_endpoint),
        "year": year,
        "total": money(sums["total"] or 0),
        "count": sums["count"],
        "monthly_count": monthly["count"],
        "monthly_total": money(monthly["total"] or 0),
    }


def recent(limit=8):
    """The latest donations that were paid, refunded or failed, of the kind Stripe takes now."""
    livemode = stripe_mode() == "live"
    return list(
        Donation.objects.filter(livemode=livemode, status__in=[Donation.PAID, Donation.REFUNDED, Donation.FAILED])
        .order_by("-paid_at", "-created_at")[:limit]
    )
