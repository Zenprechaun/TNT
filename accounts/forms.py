from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _

from emails.models import Email
from emails.sending import send

from .models import Role

User = get_user_model()


class LoginForm(AuthenticationForm):
    remember = forms.BooleanField(required=False, label=_("Keep me signed in"))

    error_messages = {
        "invalid_login": _("That email, username or password isn't right. Check them and try again."),
        "inactive": _("This account is turned off. Ask an admin to turn it back on."),
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = _("Email or username")


class RolesForm(forms.Form):
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.all(),
        error_messages={"required": _("Choose at least one role.")},
    )


class RegisterForm(forms.Form):
    """Creating an account. The email address doubles as the username."""

    first_name = forms.CharField(label=_("First name"), max_length=150,
                                 error_messages={"required": _("Enter your first name.")})
    last_name = forms.CharField(label=_("Last name"), max_length=150,
                                error_messages={"required": _("Enter your last name.")})
    email = forms.EmailField(label=_("Email"), max_length=150, error_messages={
        "required": _("Enter your email address."), "invalid": _("Enter an email address like name@example.com.")})
    password1 = forms.CharField(label=_("Password"), strip=False, widget=forms.PasswordInput,
                                error_messages={"required": _("Choose a password.")})
    password2 = forms.CharField(label=_("Password again"), strip=False, widget=forms.PasswordInput,
                                error_messages={"required": _("Enter the same password again.")})
    # Spam trap. People never see this field; bots fill it in.
    website = forms.CharField(required=False)

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

    def clean_last_name(self):
        return self.cleaned_data["last_name"].strip()

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            raise forms.ValidationError(_("There’s already an account with this email. Log in instead."))
        return email

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError(_("Leave this field empty."))
        return ""

    def clean(self):
        data = super().clean()
        first, second = data.get("password1"), data.get("password2")
        if first and second and first != second:
            self.add_error("password2", _("The two passwords don’t match."))
        elif first:
            candidate = User(username=data.get("email") or "", email=data.get("email") or "",
                             first_name=data.get("first_name") or "", last_name=data.get("last_name") or "")
            try:
                validate_password(first, candidate)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data

    def save(self):
        data = self.cleaned_data
        return User.objects.create_user(
            username=data["email"].lower(), email=data["email"], password=data["password1"],
            first_name=data["first_name"], last_name=data["last_name"],
        )


class ForgotPasswordForm(PasswordResetForm):
    """Asks for the account's email address, and emails it a link to choose a new password.

    It says the same thing whether or not there's an account with that address, so nobody can
    use it to find out who has one.
    """

    email = forms.EmailField(label=_("Email"), max_length=254, error_messages={
        "required": _("Enter your email address."), "invalid": _("Enter an email address like name@example.com.")})

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email,
                  html_email_template_name=None):
        subject = "".join(render_to_string(subject_template_name, context).splitlines())
        body = render_to_string(email_template_name, context)
        user = context.get("user")
        # The link isn't kept: anyone who could read it could change the password.
        send(Email.PASSWORD, to_email, subject, body, ref=f"user:{user.pk}" if user else "", keep_body=False)


class NewPasswordForm(SetPasswordForm):
    """Choosing a new password from the link in a password reset email."""

    error_messages = {"password_mismatch": _("The two passwords don’t match.")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = _("New password")
        self.fields["new_password1"].help_text = ""
        self.fields["new_password1"].error_messages["required"] = _("Choose a password.")
        self.fields["new_password2"].label = _("New password again")
        self.fields["new_password2"].help_text = ""
        self.fields["new_password2"].error_messages["required"] = _("Enter the same password again.")
