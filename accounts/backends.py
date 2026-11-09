from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Lets people sign in with their email address or their username, in any letter case."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        username = username.strip()
        lookup = "email__iexact" if "@" in username else f"{UserModel.USERNAME_FIELD}__iexact"
        matches = list(UserModel._default_manager.filter(**{lookup: username})[:2])
        if len(matches) == 1:
            username = matches[0].get_username()
        # The parent class checks the password, and takes the same time whether or not the account exists.
        return super().authenticate(request, username=username, password=password, **kwargs)
