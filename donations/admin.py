from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from pages.spreadsheets import csv_download

from .models import Donation, MonthlyDonation, money


def _date(value):
    return timezone.localtime(value).strftime("%Y-%m-%d") if value else ""


DONATION_HEADER = [_("Receipt"), _("Date paid"), _("Name"), _("Email"), _("Amount"), _("Fee covered"), _("Refunded"),
                   _("Frequency"), _("Status"), _("Language"), _("Real or test")]


def donation_rows(donations):
    for d in donations:
        yield [d.number, _date(d.paid_at), d.name, d.email, d.amount / 100, d.fee_covered / 100, d.amount_refunded / 100,
               d.get_frequency_display(), d.get_status_display(), d.get_language_display(),
               gettext("Real") if d.livemode else gettext("Test")]


class Payments(admin.SimpleListFilter):
    title = _("payments")
    parameter_name = "mode"

    def lookups(self, request, model_admin):
        return [("live", _("Real")), ("test", _("Test"))]

    def queryset(self, request, queryset):
        if self.value() in ("live", "test"):
            return queryset.filter(livemode=self.value() == "live")
        return queryset


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ["number_link", "paid_at", "donor_name", "amount_display", "frequency", "status", "mode"]
    list_display_links = ["number_link"]
    list_filter = ["status", "frequency", Payments, "language", "paid_at"]
    search_fields = ["name", "email", "stripe_checkout_session", "stripe_payment_intent", "stripe_invoice"]
    date_hierarchy = "created_at"
    readonly_fields = ["number_link", "user", "monthly", "frequency", "amount_display", "fee_display", "refunded_display",
                       "name", "email", "language", "livemode", "created_at", "paid_at", "receipt_sent_at",
                       "stripe_checkout_session", "stripe_payment_intent", "stripe_invoice", "stripe_customer"]
    fieldsets = [
        (None, {"fields": ["number_link", "status", "amount_display", "fee_display", "refunded_display", "frequency",
                           "monthly", "created_at", "paid_at"]}),
        (_("Donor"), {"fields": ["name", "email", "user", "language", "receipt_sent_at"]}),
        (_("Stripe"), {"fields": ["livemode", "stripe_checkout_session", "stripe_payment_intent", "stripe_invoice",
                                  "stripe_customer"], "classes": ["collapse"]}),
    ]
    actions = ["download_csv"]

    def has_add_permission(self, request):
        return False  # donations come from Stripe

    @admin.display(description=_("Receipt"), ordering="pk")
    def number_link(self, obj):
        return format_html('<span style="white-space:nowrap">{}</span>', obj.number)

    @admin.display(description=_("Donor"), ordering="name")
    def donor_name(self, obj):
        return obj.name or "–"

    @admin.display(description=_("Amount"), ordering="amount")
    def amount_display(self, obj):
        return money(obj.amount)

    @admin.display(description=_("Fee covered"))
    def fee_display(self, obj):
        return money(obj.fee_covered)

    @admin.display(description=_("Refunded"))
    def refunded_display(self, obj):
        return money(obj.amount_refunded)

    @admin.display(description=_("Payments"), boolean=False, ordering="livemode")
    def mode(self, obj):
        return gettext("Real") if obj.livemode else gettext("Test")

    @admin.action(description=_("Download the selected donations (CSV)"))
    def download_csv(self, request, queryset):
        return csv_download("donations.csv", DONATION_HEADER, donation_rows(queryset.order_by("paid_at", "pk")))


@admin.register(MonthlyDonation)
class MonthlyDonationAdmin(admin.ModelAdmin):
    list_display = ["__str__", "email", "amount_display", "status", "started_at", "ends_at", "canceled_at", "mode"]
    list_filter = ["status", Payments]
    search_fields = ["name", "email", "stripe_subscription", "stripe_customer"]
    readonly_fields = ["name", "email", "user", "amount_display", "fee_display", "status", "ends_at", "language",
                       "livemode", "started_at", "canceled_at", "stripe_subscription", "stripe_customer"]
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    @admin.display(description=_("Each month"), ordering="amount")
    def amount_display(self, obj):
        return money(obj.amount)

    @admin.display(description=_("Fee covered"))
    def fee_display(self, obj):
        return money(obj.fee_covered)

    @admin.display(description=_("Payments"), ordering="livemode")
    def mode(self, obj):
        return gettext("Real") if obj.livemode else gettext("Test")
