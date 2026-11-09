"""Web addresses for the Tahoe Neighborhood Table website."""

from django.contrib import admin
from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from django.views.i18n import JavaScriptCatalog

admin.site.site_header = "Tahoe Neighborhood Table"
admin.site.site_title = _("Tahoe Neighborhood Table admin")
admin.site.index_title = _("Site administration")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("volunteer/", include("volunteers.urls")),
    # The language switch posts here (Django's set_language view).
    path("i18n/", include("django.conf.urls.i18n")),
    # Translations for the site's scripts, in the visitor's language. Naming a package keeps it to
    # the site's own translations (locale/), without the admin's.
    path("jsi18n/", JavaScriptCatalog.as_view(packages=["pages"]), name="javascript-catalog"),
    path("", include("accounts.urls")),
    path("", include("pages.urls")),
]
