"""Web addresses for the Tahoe Neighborhood Table website."""

from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Tahoe Neighborhood Table"
admin.site.site_title = "Tahoe Neighborhood Table admin"
admin.site.index_title = "Site administration"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("volunteer/", include("volunteers.urls")),
    path("", include("accounts.urls")),
    path("", include("pages.urls")),
]
