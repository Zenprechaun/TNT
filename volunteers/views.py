from itertools import groupby

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from . import calendar, services
from .forms import SignupForm, shift_name
from .models import Event, Signup, long_day


def current_event():
    """The open event with the soonest shift, or None."""
    return Event.objects.upcoming().first()


def can_preview(request):
    """Admins can see and try an event's sign-up before sign-ups open. Nothing they send is saved."""
    return request is not None and request.user.is_authenticated and request.user.is_staff


def counts_for(event):
    return {str(s.pk): s.taken for s in event.shifts.with_taken()}


def accepting(event, now=None):
    now = now or timezone.now()
    return event.is_open and any(not s.has_started(now) for s in event.shifts.all())


def build_days(event, selected=()):
    now = timezone.now()
    days = []
    shifts = event.shifts.select_related("role").with_taken()
    for day, group in groupby(shifts, key=lambda s: s.date):
        rows = []
        for s in group:
            taken = min(s.taken, s.capacity)
            rows.append({
                "shift": s,
                "taken": taken,
                "left": s.capacity - taken,
                "full": taken >= s.capacity,
                "started": s.has_started(now),
                "selected": s.pk in selected,
                "slots": range(s.capacity) if s.capacity <= 20 else None,
                "taken_pct": round(100 * taken / s.capacity, 1),
                "from_min": int(s.starts_at.timestamp() // 60),
                "to_min": int(s.ends_at.timestamp() // 60),
                "gcal": calendar.google_link(s),
            })
        days.append({"date": day, "label": long_day(day), "rows": rows})
    return days


def signup_context(event=None, form=None, problem=None, request=None):
    """Everything the sign-up widget needs, for the home page pop-up and the full page.

    With no open event, admins get the next closed one as a preview.
    """
    if event is None:
        event = current_event()
        if event is None and can_preview(request):
            event = Event.objects.upcoming(include_closed=True).first()
    context = {"contact_email": settings.VOLUNTEER_CONTACT_EMAIL, "vol": None}
    if event is None:
        return context
    open_now = accepting(event)
    if not open_now and not can_preview(request):
        return context
    form = form or SignupForm(event=event)
    selected = set()
    if form.is_bound:
        form.mark_errors()
        selected = {int(v) for v in form.data.getlist("shifts") if str(v).isdigit()}
    days = build_days(event, selected)
    rows = [r for d in days for r in d["rows"]]
    context["vol"] = {
        "event": event,
        "form": form,
        "days": days,
        "problem": problem,
        "total_spots": sum(r["shift"].capacity for r in rows),
        "open_spots": sum(r["left"] for r in rows if not r["started"]),
        "roles": list({r["shift"].role.pk: r["shift"].role for r in rows}.values()),
        "accepting": open_now,
        "preview": not open_now,
        "send_confirmation": settings.VOLUNTEER_SEND_CONFIRMATION,
    }
    return context


def unavailable_problem(exc):
    parts = []
    if exc.full:
        names = "; ".join(shift_name(s) for s in exc.full)
        parts.append(f"{names} filled up while you were signing up.")
    if exc.already:
        names = "; ".join(shift_name(s) for s in exc.already)
        parts.append(f"You’re already signed up for {names} with this email.")
    count = len(exc.full) + len(exc.already)
    parts.append(f"We took {'it' if count == 1 else 'them'} off this sign-up. Check your shifts and confirm again.")
    title = "A shift is no longer available" if count == 1 else "Some shifts are no longer available"
    return {"title": title, "text": " ".join(parts)}


def confirmation_payload(signup):
    shifts = signup.active_shifts()
    return {
        "firstName": signup.first_name,
        "email": signup.email,
        "emailed": settings.VOLUNTEER_SEND_CONFIRMATION,
        "count": len(shifts),
        "shifts": [{
            "id": s.pk,
            "day": long_day(s.date),
            "time": s.time_range,
            "role": s.role.name,
            "where": s.where,
            "color": s.role.color,
            "gcal": calendar.google_link(s),
        } for s in shifts],
        "icsUrl": reverse("volunteers:calendar", args=[signup.event.slug, signup.token]),
        "pageUrl": reverse("volunteers:confirmed", args=[signup.event.slug, signup.token]),
    }


def start(request):
    event = current_event()
    if event is None and can_preview(request):
        event = Event.objects.upcoming(include_closed=True).first()
    if event:
        return redirect("volunteers:signup", slug=event.slug)
    return render(request, "volunteers/closed.html", {"contact_email": settings.VOLUNTEER_CONTACT_EMAIL})


@never_cache
@require_http_methods(["GET", "POST"])
def signup(request, slug):
    event = get_object_or_404(Event, slug=slug)
    wants_json = "application/json" in request.headers.get("Accept", "")

    if not accepting(event):
        if request.method == "GET" and can_preview(request):
            return render(request, "volunteers/signup_page.html", signup_context(event, request=request))
        if wants_json:
            return JsonResponse({"ok": False, "error": "closed", "title": "Sign-ups are closed",
                                 "message": "Sign-ups for this event are closed."}, status=409)
        return render(request, "volunteers/closed.html",
                      {"event": event, "contact_email": settings.VOLUNTEER_CONTACT_EMAIL})

    if request.method == "GET":
        return render(request, "volunteers/signup_page.html", signup_context(event))

    form = SignupForm(request.POST, event=event)
    if not form.is_valid():
        if wants_json:
            errors = {name: [e["message"] for e in errs] for name, errs in form.errors.get_json_data().items()}
            return JsonResponse({"ok": False, "error": "invalid", "errors": errors, "counts": counts_for(event)}, status=400)
        return render(request, "volunteers/signup_page.html", signup_context(event, form))

    try:
        signup = services.register(form)
    except services.ShiftsUnavailable as exc:
        problem = unavailable_problem(exc)
        bad = {s.pk for s in exc.full + exc.already}
        if wants_json:
            return JsonResponse({
                "ok": False, "error": "unavailable", "title": problem["title"], "message": problem["text"],
                "remove": sorted(bad), "counts": counts_for(event),
            }, status=409)
        data = request.POST.copy()
        data.setlist("shifts", [v for v in data.getlist("shifts") if not v.isdigit() or int(v) not in bad])
        return render(request, "volunteers/signup_page.html",
                      signup_context(event, SignupForm(data, event=event), problem))

    if wants_json:
        return JsonResponse({"ok": True, "confirmation": confirmation_payload(signup), "counts": counts_for(event)})
    return redirect("volunteers:confirmed", slug=event.slug, token=signup.token)


@never_cache
@require_GET
def spots(request, slug):
    event = get_object_or_404(Event, slug=slug)
    return JsonResponse({"counts": counts_for(event)})


def _signup_for(slug, token):
    return get_object_or_404(Signup.objects.select_related("event"), token=token, event__slug=slug)


@require_GET
def confirmed(request, slug, token):
    signup = _signup_for(slug, token)
    shifts = signup.active_shifts()
    return render(request, "volunteers/confirmed.html", {
        "signup": signup,
        "event": signup.event,
        "shifts": [{"shift": s, "gcal": calendar.google_link(s)} for s in shifts],
        "contact_email": settings.VOLUNTEER_CONTACT_EMAIL,
        "send_confirmation": settings.VOLUNTEER_SEND_CONFIRMATION,
    })


@require_GET
def calendar_file(request, slug, token):
    signup = _signup_for(slug, token)
    response = HttpResponse(calendar.ics(signup, signup.active_shifts()), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{signup.event.slug}-shifts.ics"'
    return response
