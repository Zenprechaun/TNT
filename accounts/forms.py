from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from .models import Role


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
