from django.contrib import admin

from .models import AccountChange


@admin.register(AccountChange)
class AccountChangeAdmin(admin.ModelAdmin):
    """Every change admins made to staff and volunteer email accounts from the Management page."""

    list_display = ["created_at", "action", "address", "kind", "manager", "by_name"]
    list_filter = ["action", "kind", "created_at"]
    search_fields = ["address", "manager", "by_name"]
    date_hierarchy = "created_at"
    fields = ["created_at", "action", "address", "kind", "manager", "by", "by_name"]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
