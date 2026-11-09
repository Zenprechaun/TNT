import re

from django import forms
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from pages.languages import current_language

from .models import Shift, Signup, clock, short_day


def shift_name(shift):
    return gettext("%(role)s, %(day)s at %(time)s") % {
        "role": shift.role.local.name, "day": short_day(shift.date), "time": clock(shift.start)}


class TelInput(forms.TextInput):
    input_type = "tel"


HINTS = {
    "email": _("We’ll contact you here about your shifts."),
    "phone": _("Only for day-of updates, like a change of start time."),
    "notes": _("Accessibility needs, lifting limits, or who you’re volunteering with. "
               "Coming as a group? Ask each person to sign up so we can plan."),
}

INPUT_ATTRS = {
    "first_name": {"autocomplete": "given-name"},
    "last_name": {"autocomplete": "family-name"},
    "email": {"autocomplete": "email", "inputmode": "email", "autocapitalize": "off", "spellcheck": "false"},
    "phone": {"autocomplete": "tel", "inputmode": "tel"},
    "emergency_name": {"autocomplete": "off"},
    "emergency_phone": {"autocomplete": "off", "inputmode": "tel"},
}


class ShiftChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return shift_name(obj)


class SignupForm(forms.ModelForm):
    shifts = ShiftChoiceField(
        queryset=Shift.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        error_messages={
            "required": _("Choose at least one shift."),
            "invalid_choice": _("One of those shifts isn’t available any more. Pick again."),
            "invalid_pk_value": _("One of those shifts isn’t available any more. Pick again."),
        },
    )
    # Spam trap. People never see this field; bots fill it in.
    website = forms.CharField(required=False)

    class Meta:
        model = Signup
        fields = ["first_name", "last_name", "email", "phone", "shirt_size", "emergency_name", "emergency_phone", "notes"]
        widgets = {"phone": TelInput, "emergency_phone": TelInput}
        labels = {"notes": _("Anything we should know?"), "emergency_name": _("Name"), "emergency_phone": _("Phone")}
        error_messages = {
            "first_name": {"required": _("Enter your first name.")},
            "last_name": {"required": _("Enter your last name.")},
            "email": {"required": _("Enter your email address."), "invalid": _("Enter an email address like name@example.com.")},
            "phone": {"required": _("Enter a phone number we can reach you on during the event.")},
        }

    def __init__(self, *args, event, **kwargs):
        kwargs.setdefault("auto_id", "vol-%s")
        super().__init__(*args, **kwargs)
        self.event = event
        self.fields["shifts"].queryset = event.shifts.select_related("role")
        self.fields["notes"].widget = forms.Textarea(attrs={"rows": 3, "maxlength": 1000})
        if event.ask_shirt_size:
            self.fields["shirt_size"].choices = [("", _("Choose a size"))] + Signup.SHIRT_SIZES
        else:
            del self.fields["shirt_size"]
        if not event.ask_emergency_contact:
            del self.fields["emergency_name"]
            del self.fields["emergency_phone"]
        # The English statement decides whether the box is shown; the label follows the page's language.
        if event.age_statement:
            self.fields["age_confirmed"] = forms.BooleanField(
                label=event.local.age_statement,
                error_messages={"required": _("Confirm that you meet the age requirement.")},
            )
        if event.agreement_statement:
            self.fields["agreed"] = forms.BooleanField(
                label=event.local.agreement_statement,
                error_messages={"required": _("Tick the box to agree to the volunteer guidelines.")},
            )
        for name, field in self.fields.items():
            if name in ("shifts", "website"):
                continue
            field.hint = HINTS.get(name, "")
            described = ([f"vol-{name}-hint"] if field.hint else []) + [f"vol-{name}-error"]
            attrs = {"aria-describedby": " ".join(described), **INPUT_ATTRS.get(name, {})}
            if not isinstance(field.widget, forms.CheckboxInput):
                attrs["class"] = "vol-input"
            field.widget.attrs.update(attrs)

    def mark_errors(self):
        """Flag fields with errors for screen readers after the form has been checked."""
        for name in self.errors:
            if name in self.fields:
                self.fields[name].widget.attrs["aria-invalid"] = "true"

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

    def clean_last_name(self):
        return self.cleaned_data["last_name"].strip()

    def clean_email(self):
        return self.cleaned_data["email"].strip()

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if len(re.sub(r"\D", "", phone)) < 7:
            raise forms.ValidationError(_("Enter a phone number with its area code."))
        return phone

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError(_("Leave this field empty."))
        return ""

    def clean_shifts(self):
        shifts = sorted(self.cleaned_data["shifts"], key=lambda s: s.starts_at)
        started = [s for s in shifts if s.has_started()]
        if started:
            raise forms.ValidationError(
                gettext("%(shift)s has already started. Pick another shift.") % {"shift": shift_name(started[0])})
        for first, second in zip(shifts, shifts[1:]):
            if first.overlaps(second):
                raise forms.ValidationError(
                    gettext("%(first)s and %(second)s overlap. Keep one of them.") % {
                        "first": shift_name(first), "second": shift_name(second)}
                )
        return shifts

    def save(self, commit=True):
        signup = super().save(commit=False)
        signup.event = self.event
        signup.age_confirmed = bool(self.cleaned_data.get("age_confirmed"))
        signup.agreed = bool(self.cleaned_data.get("agreed"))
        signup.language = current_language()
        if commit:
            signup.save()
        return signup
