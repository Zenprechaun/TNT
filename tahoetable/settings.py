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
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves CSS, JavaScript and images on the live site
    "django.contrib.sessions.middleware.SessionMiddleware",
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
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "pages.context_processors.site",
                "accounts.context_processors.account",
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

LANGUAGE_CODE = "en-us"
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

# The version of the code that's running. On the live server, automatic publishing
# (deploy/publish.sh) writes the Git commit into the REVISION file. /healthz reports it.
_REVISION_FILE = BASE_DIR / "REVISION"
SITE_REVISION = _REVISION_FILE.read_text().strip() if _REVISION_FILE.exists() else "development"

# Where automatic publishing records the result of its latest run, next to the database.
PUBLISH_STATUS_FILE = Path(DATABASES["default"]["NAME"]).parent / "publish-status.json"

if not DEBUG:
    # Nginx handles HTTPS and tells Django about it with this header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Once HTTPS works, set DJANGO_HSTS_SECONDS=31536000 so browsers always use it.
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))
    # Send warnings and errors to the server log: journalctl -u tahoetable
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"console": {"class": "logging.StreamHandler", "level": "WARNING"}},
        "root": {"handlers": ["console"], "level": "WARNING"},
    }
