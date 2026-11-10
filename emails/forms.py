from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.translation import gettext_lazy as _

from .models import EmailSettings, split_addresses


class EmailServiceForm(forms.Form):
    """Connects the site to an email service, on the Management page."""

    service = forms.ChoiceField(label=_("Email service"), choices=EmailSettings.SERVICES, widget=forms.RadioSelect)
    username = forms.CharField(label=_("Username"), required=False, max_length=255)
    password = forms.CharField(
        label=_("API key or password"), required=False, max_length=500,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "spellcheck": "false"}),
    )
    host = forms.CharField(label=_("SMTP server"), required=False, max_length=255)
    port = forms.IntegerField(label=_("Port"), required=False, min_value=1, max_value=65535)
    security = forms.ChoiceField(label=_("Security"), choices=EmailSettings.SECURITY, required=False)
    from_name = forms.CharField(label=_("Sender name"), max_length=100)
    from_address = forms.EmailField(label=_("Send from"))
    reply_to = forms.EmailField(label=_("Replies go to"), required=False)

    def __init__(self, *args, conf, **kwargs):
        self.conf = conf
        kwargs.setdefault("initial", {
            "service": conf.service or EmailSettings.RESEND,
            "username": conf.username,
            "host": conf.host if conf.service == EmailSettings.OTHER else "",
            "port": conf.port if conf.service == EmailSettings.OTHER else None,
            "security": conf.security,
            "from_name": conf.from_name,
            "from_address": conf.from_address,
            "reply_to": conf.reply_to,
        })
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(autocomplete="off", spellcheck="false", autocapitalize="none")
        self.fields["host"].widget.attrs.update(spellcheck="false", autocapitalize="none", placeholder="smtp.example.com")
        if conf.password_encrypted and not conf.password_unreadable:
            self.fields["password"].widget.attrs["placeholder"] = (
                _("Saved, ends in …%(end)s. Leave empty to keep it.") % {"end": conf.password_end}
                if conf.password_end else _("Saved. Leave empty to keep it."))

    def clean(self):
        data = super().clean()
        service = data.get("service")
        if not service:
            return data
        preset = EmailSettings.PRESETS.get(service)
        if preset:
            # The service's own SMTP settings. Only "another email service" needs them typed in.
            data["host"], data["port"], data["security"] = preset["host"], preset["port"], preset["security"]
            if "username" in preset:
                data["username"] = preset["username"]
        else:
            if not data.get("host"):
                self.add_error("host", _("Enter the SMTP server, like smtp.example.com."))
            data["security"] = data.get("security") or EmailSettings.STARTTLS
            data["port"] = data.get("port") or (465 if data["security"] == EmailSettings.SSL else 587)

        # Keys and app passwords are often copied with spaces or line breaks around them.
        password = "".join((data.get("password") or "").split())
        data["password"] = password
        same_account = (self.conf.host == data.get("host") and self.conf.username == (data.get("username") or ""))
        has_saved = bool(self.conf.password_encrypted) and not self.conf.password_unreadable and same_account
        if not password and not has_saved:
            self.add_error("password", _("Paste the API key or password from the email service."))
        if service == EmailSettings.RESEND and password and not password.startswith("re_"):
            self.add_error("password", _("A Resend API key starts with re_. Copy it again from Resend’s API Keys page."))
        if service in (EmailSettings.BREVO, EmailSettings.GOOGLE) and not data.get("username"):
            message = (_("Enter the SMTP login from Brevo’s SMTP & API page.") if service == EmailSettings.BREVO
                       else _("Enter the full Google email address, like info@tahoeneighborhoodtable.com."))
            self.add_error("username", message)
        return data

    def save(self, user):
        conf, data = self.conf, self.cleaned_data
        conf.service = data["service"]
        conf.host = data["host"].strip()
        conf.port = data["port"]
        conf.security = data["security"]
        conf.username = (data.get("username") or "").strip()
        if data["password"]:
            conf.set_password(data["password"])
        conf.from_name = data["from_name"].strip()
        conf.from_address = data["from_address"]
        conf.reply_to = data.get("reply_to") or ""
        conf.connected_at = None
        conf.updated_by = user if user.is_authenticated else None
        conf.save()
        return conf


class EmailChoicesForm(forms.ModelForm):
    """Which emails the site sends, and who hears about new volunteers."""

    class Meta:
        model = EmailSettings
        fields = ["volunteer_confirmations", "donation_receipts", "volunteer_notify"]
        widgets = {"volunteer_notify": forms.Textarea(attrs={"rows": 3, "spellcheck": "false"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["volunteer_notify"].show_hidden_initial = False

    def clean_volunteer_notify(self):
        addresses, wrong = [], []
        for address in split_addresses(self.cleaned_data.get("volunteer_notify")):
            try:
                validate_email(address)
            except ValidationError:
                wrong.append(address)
                continue
            if address.lower() not in (a.lower() for a in addresses):
                addresses.append(address)
        if wrong:
            raise ValidationError(_("These aren’t email addresses: %(addresses)s"), params={"addresses": ", ".join(wrong)})
        return "\n".join(addresses)


class TestEmailForm(forms.Form):
    to = forms.EmailField(label=_("Send it to"))
