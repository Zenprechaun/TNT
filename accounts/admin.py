"""The full admin site at /admin/: people with their roles, and the roles themselves."""

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db import models
from django.utils.translation import gettext_lazy as _

from .models import Profile, Role

User = get_user_model()


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "description", "people")
    search_fields = ("name", "slug", "description")

    @admin.display(description=_("People"))
    def people(self, role):
        return role.profiles.count()

    def get_prepopulated_fields(self, request, obj=None):
        return {} if obj else {"slug": ("name",)}

    def get_readonly_fields(self, request, obj=None):
        return ("slug",) if obj and obj.is_built_in else ()

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_built_in:
            return False
        return super().has_delete_permission(request, obj)


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fields = ("roles",)
    verbose_name = verbose_name_plural = _("Roles")
    formfield_overrides = {models.ManyToManyField: {"widget": forms.CheckboxSelectMultiple}}


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Roles replace Django's staff, superuser and group settings. The Admin role grants admin access."""

    list_display = ("username", "email", "first_name", "last_name", "role_list", "is_active", "last_login")
    list_filter = ("is_active", "profile__roles")
    filter_horizontal = ()
    readonly_fields = ("last_login", "date_joined")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "email")}),
        (_("Status"), {"fields": ("is_active",)}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("profile").prefetch_related("profile__roles")

    def get_inlines(self, request, obj):
        # New accounts get a profile automatically, so roles are set once the account is saved.
        return [ProfileInline] if obj else []

    @admin.display(description=_("Roles"))
    def role_list(self, user):
        profile = getattr(user, "profile", None)
        return ", ".join(str(role.display_name) for role in profile.roles.all()) if profile else ""
