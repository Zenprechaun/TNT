"""Saving a sign-up without overbooking a shift."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count
from django.template.loader import render_to_string

from .models import Assignment, Shift

log = logging.getLogger("volunteers")


class ShiftsUnavailable(Exception):
    """Some chosen shifts can't be booked: they filled up, or this email already has them."""

    def __init__(self, full=(), already=()):
        super().__init__("Some shifts are unavailable")
        self.full = list(full)
        self.already = list(already)


def taken_counts(shift_ids):
    rows = (
        Assignment.objects.filter(shift_id__in=shift_ids, cancelled=False)
        .values("shift_id")
        .annotate(n=Count("id"))
    )
    return {row["shift_id"]: row["n"] for row in rows}


def register(form):
    """Save a valid SignupForm. Raises ShiftsUnavailable if a shift is full or already booked by this email."""
    event = form.event
    shifts = form.cleaned_data["shifts"]
    ids = [s.pk for s in shifts]
    email = form.cleaned_data["email"]
    with transaction.atomic():
        # Lock the chosen shifts so two people can't take the last spot at the same moment.
        list(Shift.objects.select_for_update().filter(pk__in=ids, event=event).values_list("pk", flat=True))
        taken = taken_counts(ids)
        already = set(
            Assignment.objects.filter(shift_id__in=ids, cancelled=False, signup__email__iexact=email)
            .values_list("shift_id", flat=True)
        )
        full = [s for s in shifts if s.pk not in already and taken.get(s.pk, 0) >= s.capacity]
        dupes = [s for s in shifts if s.pk in already]
        if full or dupes:
            raise ShiftsUnavailable(full=full, already=dupes)
        signup = form.save()
        Assignment.objects.bulk_create([Assignment(signup=signup, shift=s) for s in shifts])
        transaction.on_commit(lambda: send_emails(signup.pk))
    return signup


def send_emails(signup_id):
    from .models import Signup

    signup = Signup.objects.select_related("event").get(pk=signup_id)
    context = {
        "signup": signup,
        "event": signup.event,
        "shifts": signup.active_shifts(),
        "contact_email": settings.VOLUNTEER_CONTACT_EMAIL,
    }
    if settings.VOLUNTEER_SEND_CONFIRMATION:
        try:
            send_mail(
                f"You’re signed up: {signup.event.name}",
                render_to_string("volunteers/email/confirmation.txt", context),
                settings.DEFAULT_FROM_EMAIL,
                [signup.email],
            )
        except Exception:
            log.exception("Couldn't send the confirmation email for sign-up %s", signup.pk)
    if settings.VOLUNTEER_NOTIFY_EMAILS:
        try:
            send_mail(
                f"New volunteer: {signup.full_name} ({signup.event.name})",
                render_to_string("volunteers/email/organizer.txt", context),
                settings.DEFAULT_FROM_EMAIL,
                settings.VOLUNTEER_NOTIFY_EMAILS,
            )
        except Exception:
            log.exception("Couldn't send the organizer email for sign-up %s", signup.pk)
