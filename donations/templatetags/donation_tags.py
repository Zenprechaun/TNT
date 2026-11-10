from django import template

from ..models import Donation, MonthlyDonation, stripe_mode
from ..summary import totals

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
    return totals()
