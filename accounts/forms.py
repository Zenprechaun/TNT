from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import Role


class LoginForm(AuthenticationForm):
    remember = forms.BooleanField(required=False, label="Keep me signed in")

    error_messages = {
        "invalid_login": "That email, username or password isn't right. Check them and try again.",
        "inactive": "This account is turned off. Ask an admin to turn it back on.",
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = "Email or username"


class RolesForm(forms.Form):
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.all(),
        error_messages={"required": "Choose at least one role."},
    )
