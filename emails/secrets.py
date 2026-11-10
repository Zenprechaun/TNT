"""Keeps the email service's password or API key encrypted in the database.

The key comes from DJANGO_SECRET_KEY, which lives in /srv/tahoetable/.env and not in the
database, so a copy of the database (a backup, say) doesn't give the password away.
If the secret key ever changes, the saved password can't be read anymore and has to be
entered again on the Management page.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    digest = hashlib.sha256(f"tahoetable.emails:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(text):
    return _fernet().encrypt(text.encode()).decode() if text else ""


def decrypt(token):
    """The original text, or "" when there's none or it can't be read with this secret key."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ""
