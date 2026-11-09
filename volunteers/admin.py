import csv

from django import forms
from django.contrib import admin
from django.db import models
from django.db.models import Count, Q
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import Assignment, Event, Role, Shift, Signup


def _cell(value):
    """Keep spreadsheet apps from running anything that looks like a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def csv_download(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")  # lets Excel read accented names correctly
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return response


ROSTER_HEADER = ["Shift", "First name", "Last name", "Email", "Phone", "T-shirt", "Emergency contact",
                 "Emergency phone", "Notes", "Signed up"]


def roster_rows(assignments):
    for a in assignments:
        s = a.signup
        yield [a.shift.long_label, s.first_name, s.last_name, s.email, s.phone, s.get_shirt_size_display(),
               s.emergency_name, s.emergency_phone, s.notes, timezone.localtime(s.created_at).strftime("%Y-%m-%d %H:%M")]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "swatch", "order"]
    list_editable = ["order"]

    @admin.display(description="Color")
    def swatch(self, obj):
        return format_html(
            '<span style="display:inline-block;width:14px;height:14px;border-radius:3px;'
            'vertical-align:middle;background:{}"></span> {}', obj.color, obj.color)


class ShiftInline(admin.TabularInline):
    model = Shift
    extra = 1
    fields = ["role", "date", "start", "end", "capacity", "where", "details", "tags", "filled"]
    readonly_fields = ["filled"]
    formfield_overrides = {models.TextField: {"widget": forms.Textarea(attrs={"rows": 2, "cols": 32})}}

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("role").with_taken()

    @admin.display(description="Signed up")
    def filled(self, obj):
        return f"{obj.taken} of {obj.capacity}" if obj.pk else "–"


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["name", "dates", "is_open", "filled", "sign_up_page"]
    list_filter = ["is_open"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [ShiftInline]
    fieldsets = [
        (None, {"fields": ["name", "slug", "is_open", "intro"]}),
        ("Where and when", {"fields": ["location", "location_url", "check_in", "good_to_know"]}),
        ("Sign-up form", {"fields": ["ask_shirt_size", "ask_emergency_contact", "age_statement", "agreement_statement"]}),
    ]

    @admin.display(description="Dates")
    def dates(self, obj):
        return obj.date_range_text() or "No shifts yet"

    @admin.display(description="Spots filled")
    def filled(self, obj):
        shifts = obj.shifts.with_taken()
        taken = sum(min(s.taken, s.capacity) for s in shifts)
        total = sum(s.capacity for s in shifts)
        return f"{taken} of {total}"

    @admin.display(description="Sign-up page")
    def sign_up_page(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">Open</a>',
                           reverse("volunteers:signup", args=[obj.slug]))


class RosterInline(admin.TabularInline):
    model = Assignment
    extra = 0
    fields = ["volunteer", "email", "phone", "signed_up", "cancelled"]
    readonly_fields = ["volunteer", "email", "phone", "signed_up"]
    verbose_name = "volunteer"
    verbose_name_plural = "Roster"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("signup")

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Volunteer")
    def volunteer(self, obj):
        return format_html('<a href="{}">{}</a>',
                           reverse("admin:volunteers_signup_change", args=[obj.signup_id]), obj.signup.full_name)

    @admin.display(description="Email")
    def email(self, obj):
        return obj.signup.email

    @admin.display(description="Phone")
    def phone(self, obj):
        return obj.signup.phone

    @admin.display(description="Signed up")
    def signed_up(self, obj):
        return timezone.localtime(obj.created_at).strftime("%b %d, %I:%M %p")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ["__str__", "event", "date", "start", "end", "filled"]
    list_filter = ["event", "role", "date"]
    list_select_related = ["role", "event"]
    inlines = [RosterInline]
    actions = ["download_roster"]

    def get_queryset(self, request):
        return super().get_queryset(request).with_taken()

    @admin.display(description="Signed up")
    def filled(self, obj):
        return f"{obj.taken} of {obj.capacity}"

    @admin.action(description="Download the roster for the selected shifts (CSV)")
    def download_roster(self, request, queryset):
        assignments = (Assignment.objects.filter(shift__in=queryset, cancelled=False)
                       .select_related("signup", "shift__role", "shift__event")
                       .order_by("shift__date", "shift__start", "signup__last_name"))
        return csv_download("volunteer-roster.csv", ROSTER_HEADER, roster_rows(assignments))


class SignupShiftsInline(admin.TabularInline):
    model = Assignment
    extra = 0
    fields = ["shift", "cancelled"]
    verbose_name = "shift"
    verbose_name_plural = "Shifts"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("shift__role")


@admin.register(Signup)
class SignupAdmin(admin.ModelAdmin):
    list_display = ["full_name", "email", "phone", "event", "shift_count", "created_at"]
    list_filter = ["event", "created_at"]
    search_fields = ["first_name", "last_name", "email", "phone"]
    readonly_fields = ["created_at", "age_confirmed", "agreed"]
    fields = ["event", "first_name", "last_name", "email", "phone", "shirt_size", "emergency_name",
              "emergency_phone", "notes", "age_confirmed", "agreed", "created_at"]
    inlines = [SignupShiftsInline]
    actions = ["download_csv"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("event").annotate(
            n_shifts=Count("assignments", filter=Q(assignments__cancelled=False)))

    @admin.display(description="Name", ordering="last_name")
    def full_name(self, obj):
        return obj.full_name

    @admin.display(description="Shifts", ordering="n_shifts")
    def shift_count(self, obj):
        return obj.n_shifts

    @admin.action(description="Download the selected sign-ups with their shifts (CSV)")
    def download_csv(self, request, queryset):
        assignments = (Assignment.objects.filter(signup__in=queryset, cancelled=False)
                       .select_related("signup", "shift__role", "shift__event")
                       .order_by("shift__date", "shift__start", "signup__last_name"))
        return csv_download("volunteer-signups.csv", ROSTER_HEADER, roster_rows(assignments))
