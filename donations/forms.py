from decimal import Decimal, InvalidOperation

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import MAX_CENTS, MIN_CENTS, PRESETS, Donation, fee_for, money


class DonateForm(forms.Form):
    frequency = forms.ChoiceField(choices=Donation.FREQUENCIES, initial=Donation.ONE_TIME)
    amount = forms.ChoiceField(
        choices=[(str(p), money(p * 100)) for p in PRESETS] + [("other", _("Other"))],
        error_messages={"required": _("Choose an amount."), "invalid_choice": _("Choose an amount.")},
    )
    other_amount = forms.CharField(required=False, max_length=12)
    cover_fee = forms.BooleanField(required=False)
    # Spam trap. People never see this field; bots fill it in.
    website = forms.CharField(required=False)

    DEFAULT_AMOUNT = {Donation.ONE_TIME: "50", Donation.MONTHLY: "25"}

    @classmethod
    def initial_from(cls, query):
        """Starting choices from the address, so 'Log in' and 'Back' don't lose what was picked."""
        frequency = query.get("frequency")
        if frequency not in dict(Donation.FREQUENCIES):
            frequency = Donation.ONE_TIME
        initial = {"frequency": frequency, "amount": cls.DEFAULT_AMOUNT[frequency],
                   "cover_fee": query.get("cover_fee") in ("1", "on", "true")}
        amount = (query.get("amount") or "").strip()
        if amount in {str(p) for p in PRESETS}:
            initial["amount"] = amount
        elif amount:
            initial["amount"], initial["other_amount"] = "other", amount
        return initial

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError(_("Leave this field empty."))
        return ""

    def clean(self):
        data = super().clean()
        choice = data.get("amount")
        cents = None
        if choice == "other":
            text = (data.get("other_amount") or "").strip().replace("$", "").replace(",", "")
            if not text:
                self.add_error("other_amount", _("Enter an amount."))
            else:
                try:
                    value = Decimal(text)
                except InvalidOperation:
                    value = None
                if value is None or not value.is_finite() or value != value.quantize(Decimal("0.01")):
                    self.add_error("other_amount", _("Enter an amount in dollars, like 40 or 37.50."))
                else:
                    cents = int(value * 100)
        elif choice:
            cents = int(choice) * 100
        if cents is not None:
            field = "other_amount" if choice == "other" else "amount"
            if cents < MIN_CENTS:
                self.add_error(field, _("The smallest donation we can take online is %(amount)s.")
                               % {"amount": money(MIN_CENTS)})
                cents = None
            elif cents > MAX_CENTS:
                self.add_error(field, _("For a donation over %(amount)s, please email us and we’ll help.")
                               % {"amount": money(MAX_CENTS)})
                cents = None
        data["cents"] = cents
        data["fee"] = fee_for(cents) if cents and data.get("cover_fee") else 0
        return data
