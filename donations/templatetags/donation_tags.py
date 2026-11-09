from django import template
from django.db.models import Count, Q, Sum
from django.utils import timezone

from ..models import Donation, MonthlyDonation, money, stripe_mode

register = template.Library()


@register.inclusion_tag("donations/_your_donations.html", takes_context=True)
def your_donations(context):
    """The donations card on the User's Dashboard: their receipts and any monthly donation."""
    user = context["request"].user
    donations = (Donation.objects.filter(user=user, status__in=[Donation.PAID, Donation.REFUNDED])
                 .order_by("-paid_at")[:24])
    monthly = MonthlyDonation.objects.filter(user=user, status__in=["active", "past_due"]).first()
    return {
        "donations": donations,
        "monthly": monthly,
        "can_manage": bool(monthly and stripe_mode()),
        "csrf_token": context.get("csrf_token"),
    }


@register.inclusion_tag("donations/_summary.html")
def donation_summary():
    """The donations card on the Admin's Dashboard: this year's total and the monthly donors."""
    livemode = stripe_mode() == "live"
    year = timezone.localdate().year
    paid = Donation.objects.filter(status=Donation.PAID, livemode=livemode, paid_at__year=year)
    totals = paid.aggregate(total=Sum("amount"), count=Count("pk"), donors=Count("email", distinct=True))
    monthly = MonthlyDonation.objects.filter(livemode=livemode, status__in=["active", "past_due"]).aggregate(
        count=Count("pk"), total=Sum("amount"))
    return {
        "connected": bool(stripe_mode()),
        "livemode": livemode,
        "year": year,
        "total": money(totals["total"] or 0),
        "count": totals["count"],
        "monthly_count": monthly["count"],
        "monthly_total": money(monthly["total"] or 0),
    }
