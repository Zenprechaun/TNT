from django.conf import settings


def site(request):
    """Details shown across the site, such as the contact email."""
    return {"site_email": settings.SITE_EMAIL}
