"""Adds the sample Tahoe Community Thanksgiving event, with sign-ups closed.

Admins can preview it from the Volunteer button. Edit its details and shifts in the admin
(Volunteers > Events), then tick "Sign-ups open" to let volunteers sign up. Volunteers
never see it while sign-ups are closed. Deleting it is fine; it won't come back.
"""
from datetime import date, time

from django.db import migrations

ROLES = [
    ("Setup crew", "#425b76", 10),
    ("Kitchen crew", "#5f633f", 20),
    ("Greeters and check-in", "#7f9cc0", 30),
    ("Serving line", "#a75531", 40),
    ("Meal delivery drivers", "#1d3249", 50),
    ("Warm clothing table", "#8e905a", 60),
    ("Cleanup crew", "#8d9178", 70),
]

WED, THU = date(2026, 11, 25), date(2026, 11, 26)
SHIFTS = [
    ("Setup crew", WED, time(14), time(17), 8, "Dining hall",
     "Set up tables, chairs, signs and the serving line.", "Lifting up to 30 lb"),
    ("Kitchen crew", WED, time(15), time(19), 10, "Kitchen",
     "Peel, chop and roast vegetables and get the stuffing ready for tomorrow.", ""),
    ("Kitchen crew", THU, time(8), time(11), 10, "Kitchen",
     "Carve turkeys, warm the sides and plate desserts.", "Closed-toe shoes"),
    ("Greeters and check-in", THU, time(10, 30), time(13, 30), 4, "Front entrance",
     "Welcome guests, help them find a seat and answer questions.", "Spanish speakers especially welcome"),
    ("Serving line", THU, time(11), time(14), 12, "Dining hall",
     "Serve plates, refill drinks and visit with guests.", ""),
    ("Meal delivery drivers", THU, time(11), time(13), 6, "Kitchen door",
     "Deliver warm meals to neighbors who can’t come in.", "Valid license and your own car"),
    ("Warm clothing table", THU, time(11), time(14), 4, "Lobby",
     "Help guests choose coats, blankets and hats from donated items.", ""),
    ("Cleanup crew", THU, time(14), time(16, 30), 10, "Dining hall and kitchen",
     "Wash dishes, pack leftovers and reset the hall.", "Lifting up to 30 lb"),
]


def add_sample_event(apps, schema_editor):
    Event = apps.get_model("volunteers", "Event")
    Role = apps.get_model("volunteers", "Role")
    Shift = apps.get_model("volunteers", "Shift")
    if Event.objects.filter(slug="community-thanksgiving-2026").exists():
        return
    roles = {}
    for name, color, order in ROLES:
        roles[name], _ = Role.objects.get_or_create(name=name, defaults={"color": color, "order": order})
    event = Event.objects.create(
        slug="community-thanksgiving-2026",
        name="Tahoe Community Thanksgiving",
        is_open=False,
        intro="Help us share a Thanksgiving meal with our neighbors. Choose the shifts that fit your "
              "holiday. No experience needed. A team lead will show you what to do.",
        location="To be announced",
        check_in="Check in at the volunteer table 10 minutes before your shift starts.",
        good_to_know="Wear closed-toe shoes and clothes that can get a little messy.\n"
                     "Ages 14 to 17 are welcome with a parent or guardian on the same shift.\n"
                     "Back-to-back shifts are fine.",
        age_statement="I’m 18 or older, or I’ll volunteer with my parent or guardian on the same shift.",
        agreement_statement="I’ll follow the volunteer guidelines and directions from staff on site.",
    )
    for role, day, start, end, capacity, where, details, tags in SHIFTS:
        Shift.objects.create(event=event, role=roles[role], date=day, start=start, end=end,
                             capacity=capacity, where=where, details=details, tags=tags)


class Migration(migrations.Migration):
    dependencies = [("volunteers", "0001_initial")]

    operations = [migrations.RunPython(add_sample_event, migrations.RunPython.noop)]
