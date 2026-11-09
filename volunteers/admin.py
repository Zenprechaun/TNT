from django import forms
from django.contrib import admin
from django.db import models
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.html import format_html
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from pages.spreadsheets import csv_download

from .models import Assignment, Event, Role, Shift, Signup


ROSTER_HEADER = [_("Shift"), _("First name"), _("Last name"), _("Email"), _("Phone"), _("T-shirt"),
                 _("Emergency contact"), _("Emergency phone"), _("Notes"), _("Language"), _("Signed up")]


def roster_rows(assignments):
    for a in assignments:
        s = a.signup
        yield [a.shift.long_label, s.first_name, s.last_name, s.email, s.phone, s.get_shirt_size_display(),
               s.emergency_name, s.emergency_phone, s.notes, s.get_language_display(),
               timezone.localtime(s.created_at).strftime("%Y-%m-%d %H:%M")]


def filled_text(taken, total):
    return gettext("%(taken)s of %(total)s") % {"taken": taken, "total": total}


SIDE_BY_SIDE = _("Each English box has a Spanish one beside it. Visitors who switch the site to Spanish "
                 "see the Spanish text, or the English text where the Spanish box is empty.")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "name_es", "swatch", "order"]
    list_editable = ["name_es", "order"]

    @admin.display(description=_("Color"))
    def swatch(self, obj):
        return format_html(
            '<span style="display:inline-block;width:14px;height:14px;border-radius:3px;'
            'vertical-align:middle;background:{}"></span> {}', obj.color, obj.color)


class ShiftInline(admin.StackedInline):
    model = Shift
    extra = 1
    fieldsets = [(None, {"fields": [
        ("role", "date", "start", "end", "capacity", "filled"),
        ("where", "where_es"),
        ("details", "details_es"),
        ("tags", "tags_es"),
    ]})]
    readonly_fields = ["filled"]
    formfield_overrides = {models.TextField: {"widget": forms.Textarea(attrs={"rows": 2, "cols": 40})}}

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("role").with_taken()

    @admin.display(description=_("Spots filled"))
    def filled(self, obj):
        return filled_text(obj.taken, obj.capacity) if obj.pk else "–"


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["name", "dates", "is_open", "filled", "sign_up_page"]
    list_filter = ["is_open"]
    search_fields = ["name", "name_es"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [ShiftInline]
    fieldsets = [
        (None, {"fields": [("name", "name_es"), "slug", "is_open", ("intro", "intro_es")],
                "description": SIDE_BY_SIDE}),
        (_("Where and when"), {"fields": [("location", "location_es"), "location_url", ("check_in", "check_in_es"),
                                          ("good_to_know", "good_to_know_es")]}),
        (_("Sign-up form"), {"fields": ["ask_shirt_size", "ask_emergency_contact", ("age_statement", "age_statement_es"),
                                        ("agreement_statement", "agreement_statement_es")]}),
    ]
    formfield_overrides = {models.TextField: {"widget": forms.Textarea(attrs={"rows": 4, "cols": 40})}}

    @admin.display(description=_("Dates"))
    def dates(self, obj):
        return obj.date_range_text() or gettext("No shifts yet")

    @admin.display(description=_("Spots filled"))
    def filled(self, obj):
        shifts = obj.shifts.with_taken()
        taken = sum(min(s.taken, s.capacity) for s in shifts)
        total = sum(s.capacity for s in shifts)
        return filled_text(taken, total)

    @admin.display(description=_("Sign-up page"))
    def sign_up_page(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>',
                           reverse("volunteers:signup", args=[obj.slug]), gettext("Open"))


class RosterInline(admin.TabularInline):
    model = Assignment
    extra = 0
    fields = ["volunteer", "email", "phone", "language", "signed_up", "cancelled"]
    readonly_fields = ["volunteer", "email", "phone", "language", "signed_up"]
    verbose_name = _("volunteer")
    verbose_name_plural = _("Roster")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("signup")

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Volunteer"))
    def volunteer(self, obj):
        return format_html('<a href="{}">{}</a>',
                           reverse("admin:volunteers_signup_change", args=[obj.signup_id]), obj.signup.full_name)

    @admin.display(description=_("Email"))
    def email(self, obj):
        return obj.signup.email

    @admin.display(description=_("Phone"))
    def phone(self, obj):
        return obj.signup.phone

    @admin.display(description=_("Language"))
    def language(self, obj):
        return obj.signup.get_language_display()

    @admin.display(description=_("Signed up"))
    def signed_up(self, obj):
        return formats.date_format(timezone.localtime(obj.created_at), "SHORT_DATETIME_FORMAT")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ["__str__", "event", "date", "start", "end", "filled"]
    list_filter = ["event", "role", "date"]
    list_select_related = ["role", "event"]
    fieldsets = [
        (None, {"fields": ["event", ("role", "date", "start", "end", "capacity")]}),
        (_("What they’ll do"), {"fields": [("where", "where_es"), ("details", "details_es"), ("tags", "tags_es")],
                                "description": SIDE_BY_SIDE}),
    ]
    inlines = [RosterInline]
    actions = ["download_roster"]

    def get_queryset(self, request):
        return super().get_queryset(request).with_taken()

    @admin.display(description=_("Spots filled"))
    def filled(self, obj):
        return filled_text(obj.taken, obj.capacity)

    @admin.action(description=_("Download the roster for the selected shifts (CSV)"))
    def download_roster(self, request, queryset):
        assignments = (Assignment.objects.filter(shift__in=queryset, cancelled=False)
                       .select_related("signup", "shift__role", "shift__event")
                       .order_by("shift__date", "shift__start", "signup__last_name"))
        return csv_download("volunteer-roster.csv", ROSTER_HEADER, roster_rows(assignments))


class SignupShiftsInline(admin.TabularInline):
    model = Assignment
    extra = 0
    fields = ["shift", "cancelled"]
    verbose_name = _("shift")
    verbose_name_plural = _("Shifts")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("shift__role")


@admin.register(Signup)
class SignupAdmin(admin.ModelAdmin):
    list_display = ["full_name", "email", "phone", "event", "shift_count", "language", "created_at"]
    list_filter = ["event", "language", "created_at"]
    search_fields = ["first_name", "last_name", "email", "phone"]
    readonly_fields = ["created_at", "age_confirmed", "agreed", "language"]
    fields = ["event", "first_name", "last_name", "email", "phone", "shirt_size", "emergency_name",
              "emergency_phone", "notes", "age_confirmed", "agreed", "language", "created_at"]
    inlines = [SignupShiftsInline]
    actions = ["download_csv"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("event").annotate(
            n_shifts=Count("assignments", filter=Q(assignments__cancelled=False)))

    @admin.display(description=_("Name"), ordering="last_name")
    def full_name(self, obj):
        return obj.full_name

    @admin.display(description=_("Shifts"), ordering="n_shifts")
    def shift_count(self, obj):
        return obj.n_shifts

    @admin.action(description=_("Download the selected sign-ups with their shifts (CSV)"))
    def download_csv(self, request, queryset):
        assignments = (Assignment.objects.filter(signup__in=queryset, cancelled=False)
                       .select_related("signup", "shift__role", "shift__event")
                       .order_by("shift__date", "shift__start", "signup__last_name"))
        return csv_download("volunteer-signups.csv", ROSTER_HEADER, roster_rows(assignments))
