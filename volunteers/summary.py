"""Volunteer events at a glance, for the Management page."""

from django.db.models import Count, Q

from .models import Event, Signup
from .views import accepting


def upcoming_events(limit=8):
    """Events with a shift today or later, soonest first, open or not, with how full they are."""
    rows = []
    for event in Event.objects.upcoming(include_closed=True).prefetch_related("shifts")[:limit]:
        shifts = list(event.shifts.with_taken())
        taken = sum(min(s.taken, s.capacity) for s in shifts)
        total = sum(s.capacity for s in shifts)
        rows.append({
            "event": event,
            "dates": event.date_range_text(),
            "taken": taken,
            "total": total,
            "percent": round(100 * taken / total) if total else 0,
            "accepting": accepting(event),
            "signups": event.signups.filter(assignments__cancelled=False).distinct().count(),
        })
    return rows


def recent_signups(limit=8):
    return list(
        Signup.objects.select_related("event")
        .annotate(shift_count=Count("assignments", filter=Q(assignments__cancelled=False)))
        .order_by("-created_at")[:limit]
    )
