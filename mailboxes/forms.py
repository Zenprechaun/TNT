import re

from django import forms
from django.utils.translation import gettext_lazy as _

from .google import UNIT_PATTERN
from .models import KINDS
USERNAME = re.compile(r"^[a-z0-9](?:[a-z0-9._'-]{0,62}[a-z0-9])?$")


def _unit(value):
    value = (value or "").strip()
    if value and not value.startswith("/"):
        value = "/" + value
    value = value.rstrip("/") or "/"
    if value == "/" or not UNIT_PATTERN.match(value):
        raise forms.ValidationError(_("Enter the organizational unit’s path, like /Volunteers."))
    return value


def manager_choices(staff, exclude=""):
    """Active staff accounts, for choosing someone's manager."""
    return [("", _("No manager"))] + [(a.email, f"{a.name} ({a.email})") for a in staff if a.email != exclude]


class ConnectionForm(forms.Form):
    """The OAuth client from Google Cloud, and which organizational units hold staff and volunteers."""

    client_id = forms.CharField(label=_("OAuth client ID"), max_length=255)
    client_secret = forms.CharField(
        label=_("OAuth client secret"), required=False, max_length=255,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "spellcheck": "false"}),
    )
    domain = forms.CharField(label=_("Domain"), max_length=255)
    staff_unit = forms.CharField(label=_("Staff organizational unit"), max_length=255)
    volunteer_unit = forms.CharField(label=_("Volunteer organizational unit"), max_length=255)

    def __init__(self, *args, conn, **kwargs):
        self.conn = conn
        kwargs.setdefault("auto_id", "google_%s")
        kwargs.setdefault("initial", {"client_id": conn.client_id, "domain": conn.domain,
                                      "staff_unit": conn.staff_unit, "volunteer_unit": conn.volunteer_unit})
        super().__init__(*args, **kwargs)
        for name in ("client_id", "domain", "staff_unit", "volunteer_unit"):
            self.fields[name].widget.attrs.update(spellcheck="false", autocapitalize="none", autocomplete="off")
        if conn.client_secret:
            self.fields["client_secret"].widget.attrs["placeholder"] = _("Saved. Leave empty to keep it.")

    def clean_client_id(self):
        value = "".join(self.cleaned_data["client_id"].split())
        if not value.endswith(".apps.googleusercontent.com"):
            raise forms.ValidationError(_("Copy the client ID from Google Cloud. It ends in .apps.googleusercontent.com."))
        return value

    def clean_domain(self):
        value = self.cleaned_data["domain"].strip().lower().lstrip("@")
        if "." not in value or "@" in value or " " in value:
            raise forms.ValidationError(_("Enter the domain only, like tahoeneighborhoodtable.com."))
        return value

    def clean_staff_unit(self):
        return _unit(self.cleaned_data["staff_unit"])

    def clean_volunteer_unit(self):
        return _unit(self.cleaned_data["volunteer_unit"])

    def clean(self):
        data = super().clean()
        staff, volunteers = data.get("staff_unit"), data.get("volunteer_unit")
        if staff and volunteers and (staff == volunteers or staff.startswith(volunteers + "/")
                                     or volunteers.startswith(staff + "/")):
            self.add_error("volunteer_unit", _("Staff and volunteers need separate organizational units."))
        secret = "".join((data.get("client_secret") or "").split())
        data["client_secret"] = secret
        if not secret and (not self.conn.client_secret or data.get("client_id") != self.conn.client_id):
            self.add_error("client_secret", _("Paste the client secret from Google Cloud."))
        return data

    def save(self, user):
        conn, data = self.conn, self.cleaned_data
        if data["client_id"] != conn.client_id or data["domain"] != conn.domain:
            # A different OAuth client or domain means signing in again.
            conn.refresh_token_encrypted = conn.connected_as = ""
            conn.connected_at = None
        conn.client_id = data["client_id"]
        if data["client_secret"]:
            conn.set_client_secret(data["client_secret"])
        conn.domain = data["domain"]
        conn.staff_unit = data["staff_unit"]
        conn.volunteer_unit = data["volunteer_unit"]
        conn.updated_by = user
        conn.save()
        return conn


class NewAccountForm(forms.Form):
    first_name = forms.CharField(label=_("First name"), max_length=60)
    last_name = forms.CharField(label=_("Last name"), max_length=60)
    username = forms.CharField(label=_("Email address"), max_length=64)
    kind = forms.ChoiceField(label=_("Staff or volunteer"), choices=KINDS, initial="volunteer", widget=forms.RadioSelect)
    manager = forms.ChoiceField(label=_("Manager"), required=False, choices=[])
    agreed = forms.BooleanField(
        label=_("They’ve agreed in writing that Tahoe Neighborhood Table may read their organization email."),
        error_messages={"required": _("Get their written agreement before creating the account.")},
    )

    def __init__(self, *args, staff=(), domain, **kwargs):
        self.domain = domain
        kwargs.setdefault("auto_id", "acct_%s")
        super().__init__(*args, **kwargs)
        self.fields["manager"].choices = manager_choices(staff)
        self.fields["username"].widget.attrs.update(spellcheck="false", autocapitalize="none", autocomplete="off")

    def clean_username(self):
        value = self.cleaned_data["username"].strip().lower()
        local, _at, domain = value.partition("@")
        if domain and domain != self.domain:
            raise forms.ValidationError(_("The address has to end in @%(domain)s.") % {"domain": self.domain})
        if not USERNAME.match(local) or ".." in local:
            raise forms.ValidationError(_("Use letters, numbers, dots, dashes or underscores, like jane.doe."))
        return local

    @property
    def email(self):
        return f"{self.cleaned_data['username']}@{self.domain}"


class ChangeAccountForm(forms.Form):
    email = forms.EmailField()
    kind = forms.ChoiceField(choices=KINDS)
    manager = forms.ChoiceField(required=False, choices=[])

    def __init__(self, *args, staff=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].choices = manager_choices(staff, exclude=(self.data.get("email") or "").lower())
