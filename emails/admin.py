from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Email


@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    """Every email the site sent in the last six months. Send them again from the Management page."""

    list_display = ["created_at", "kind", "to", "subject", "status"]
    list_filter = ["status", "kind", "created_at"]
    search_fields = ["to", "subject"]
    date_hierarchy = "created_at"
    fields = ["kind", "to", "subject", "status", "problem_display", "error", "created_at", "sent_at", "attempts",
              "language", "body"]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description=_("problem"))
    def problem_display(self, obj):
        return obj.problem_text or "–"
