from urllib.parse import quote

from django.conf import settings
from django.urls import reverse
from django.utils.translation import gettext

from .models import stripe_mode


def donate(request):
    """Where the Donate buttons go: the donation page once Stripe is connected, otherwise an email.

    Before Stripe is connected, admins (staff) still get the donation page, as a preview.
    """
    user = getattr(request, "user", None)
    if stripe_mode() or (user is not None and user.is_authenticated and user.is_staff):
        url = reverse("donations:donate")
    else:
        url = f"mailto:{settings.SITE_EMAIL}?subject={quote(gettext('Donating to Tahoe Neighborhood Table'))}"
    return {"donate_url": url}
