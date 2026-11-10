"""
Settings for the Tahoe Neighborhood Table website.

Local development works without any setup. On the live server, settings come from
environment variables in /srv/tahoetable/.env, which deploy/setup_server.sh creates.
See deploy/env.example and DEPLOY-HOSTINGER.md.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_flag(name, default):
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_flag("DJANGO_DEBUG", "true")

_LOCAL_SECRET_KEY = "django-insecure-local-development-only"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _LOCAL_SECRET_KEY)
if not DEBUG and SECRET_KEY == _LOCAL_SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY before running with DJANGO_DEBUG=false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "pages.apps.PagesConfig",
    "emails.apps.EmailsConfig",
    "mailboxes.apps.MailboxesConfig",
    "volunteers.apps.VolunteersConfig",
    "donations.apps.DonationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves CSS, JavaScript and images on the live site
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Picks English or Spanish for each visitor: their choice from the language switch, or else
    # their browser's language.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "tahoetable.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "pages.context_processors.site",
                "accounts.context_processors.account",
                "donations.context_processors.donate",
            ],
        },
    },
]

WSGI_APPLICATION = "tahoetable.wsgi.application"

# On the live server the database sits outside the code folder, so updates never replace it.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH") or BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            # Lets SQLite serve several visitors at once without "database is locked" errors.
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# People sign in with their username or their email address (see accounts/backends.py).
AUTHENTICATION_BACKENDS = ["accounts.backends.EmailOrUsernameBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "pages:home"

# The site is in English and Spanish. The switch at the top of each page changes the language.
# See README.md, "English and Spanish".
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("es", "Español")]
LOCALE_PATHS = [BASE_DIR / "locale"]
FORMAT_MODULE_PATH = ["tahoetable.formats"]
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365  # remember the choice for a year
LANGUAGE_COOKIE_SAMESITE = "Lax"
TIME_ZONE = "America/Los_Angeles"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT") or BASE_DIR / "staticfiles")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # On the live site, file names include a fingerprint so browsers can cache them for a long time.
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Used for the Donate, Volunteer and contact links across the site.
SITE_EMAIL = "info@tahoeneighborhoodtable.com"
# The site's own address, for links in emails and for Stripe to send payment updates to.
SITE_URL = os.environ.get("SITE_URL", "https://tahoeneighborhoodtable.com")

# Email. The site sends email through an email service such as Resend, connected on the
# Management page (/dashboard/manage/#email), which also lists every email the site sent.
# Until a service is connected there, or EMAIL_HOST is set in /srv/tahoetable/.env, the site
# doesn't send email. See the emails app and DEPLOY-HOSTINGER.md, "Turning on email".
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = env_flag("EMAIL_USE_SSL", "false")
EMAIL_USE_TLS = env_flag("EMAIL_USE_TLS", "false" if EMAIL_USE_SSL else "true")
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", f"Tahoe Neighborhood Table <{SITE_EMAIL}>")
# How long a password reset link works: 3 days.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 3

# Volunteer sign-ups (the volunteers app).
VOLUNTEER_CONTACT_EMAIL = SITE_EMAIL
# Organizers to tell about each new sign-up, separated by commas. This only fills in the list the
# first time; after that, change it on the Management page.
VOLUNTEER_NOTIFY_EMAILS = env_list("VOLUNTEER_NOTIFY_EMAILS")

# Donations through Stripe (the donations app). Until STRIPE_SECRET_KEY is set in
# /srv/tahoetable/.env, the Donate button opens an email instead, and admins see a preview.
# A key starting sk_test_ or rk_test_ takes test payments only; sk_live_ or rk_live_ takes real ones.
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
# Optional. `manage.py connect_stripe` sets up the webhook and stores its secret in the database.
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
# Receipts say donations are tax-deductible (501(c)(3)). Set to false if that stops being true.
DONATIONS_TAX_DEDUCTIBLE = env_flag("DONATIONS_TAX_DEDUCTIBLE", "true")
# The organization's EIN, printed on receipts when set.
DONATIONS_TAX_ID = os.environ.get("DONATIONS_TAX_ID", "")
# What Stripe charges per card payment, used to offer donors the option to cover it.
DONATION_FEE_PERCENT = float(os.environ.get("DONATION_FEE_PERCENT", "2.9"))
DONATION_FEE_CENTS = int(os.environ.get("DONATION_FEE_CENTS", "30"))

# The version of the code that's running. On the live server, automatic publishing
# (deploy/publish.sh) writes the Git commit into the REVISION file. /healthz reports it.
_REVISION_FILE = BASE_DIR / "REVISION"
SITE_REVISION = _REVISION_FILE.read_text().strip() if _REVISION_FILE.exists() else "development"

# Where automatic publishing records the result of its latest run, next to the database.
PUBLISH_STATUS_FILE = Path(DATABASES["default"]["NAME"]).parent / "publish-status.json"
# Where deploy/backup_db.sh keeps the nightly copies of the database: /srv/tahoetable/backups.
BACKUP_DIR = Path(os.environ.get("DJANGO_BACKUP_DIR") or Path(DATABASES["default"]["NAME"]).parent.parent / "backups")
# The code on GitHub, for links from the Management page.
GITHUB_REPOSITORY_URL = os.environ.get("GITHUB_REPOSITORY_URL", "https://github.com/Zenprechaun/TNT")

if not DEBUG:
    # Nginx handles HTTPS and tells Django about it with this header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    LANGUAGE_COOKIE_SECURE = True
    # Once HTTPS works, set DJANGO_HSTS_SECONDS=31536000 so browsers always use it.
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))
    # Send warnings and errors to the server log: journalctl -u tahoetable
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"console": {"class": "logging.StreamHandler", "level": "WARNING"}},
        "root": {"handlers": ["console"], "level": "WARNING"},
    }
