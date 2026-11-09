"""Calendar links and .ics files for confirmed shifts."""
from datetime import timezone as dt_timezone
from urllib.parse import urlencode

from django.conf import settings
from django.utils import timezone


def stamp(dt):
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def title(shift):
    return f"Volunteer: {shift.role.name}, {shift.event.name}"


def details(shift):
    parts = [
        f"{shift.role.name}, {shift.where}" if shift.where else shift.role.name,
        shift.details,
        shift.event.check_in,
        f"Questions: {settings.VOLUNTEER_CONTACT_EMAIL}" if settings.VOLUNTEER_CONTACT_EMAIL else "",
    ]
    return "\n\n".join(p for p in parts if p)


def google_link(shift):
    query = urlencode({
        "action": "TEMPLATE",
        "text": title(shift),
        "dates": f"{stamp(shift.starts_at)}/{stamp(shift.ends_at)}",
        "details": details(shift),
        "location": shift.event.location,
    })
    return f"https://calendar.google.com/calendar/render?{query}"


def _escape(text):
    return (str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line):
    """Lines longer than 75 bytes continue on the next line after a space."""
    out, current, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 75:
            out.append(current)
            current, size = " ", 1
        current += ch
        size += n
    out.append(current)
    return "\r\n".join(out)


def ics(signup, shifts):
    now = stamp(timezone.now())
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Tahoe Neighborhood Table//Volunteer sign-up//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for shift in shifts:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{signup.token}-{shift.pk}@tahoeneighborhoodtable.com",
            f"DTSTAMP:{now}",
            f"DTSTART:{stamp(shift.starts_at)}",
            f"DTEND:{stamp(shift.ends_at)}",
            f"SUMMARY:{_escape(title(shift))}",
        ]
        if shift.event.location:
            lines.append(f"LOCATION:{_escape(shift.event.location)}")
        lines += [f"DESCRIPTION:{_escape(details(shift))}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
