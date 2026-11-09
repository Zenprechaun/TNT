from django.conf import settings
from django.utils.translation import get_language


def current_language():
    """The language of this page, as one of settings.LANGUAGES."""
    codes = dict(settings.LANGUAGES)
    language = get_language() or settings.LANGUAGE_CODE
    for code in (language, language.split("-")[0]):
        if code in codes:
            return code
    return settings.LANGUAGE_CODE
