import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Count, Min, Q
from django.utils import dateformat, timezone


def event_zone():
    return ZoneInfo(settings.TIME_ZONE)


def clock(t):
    """9:00 AM style, the same on every operating system."""
    return dateformat.time_format(t, "g:i A")


def long_day(d):
    return dateformat.format(d, "l, F j")


def short_day(d):
    return dateformat.format(d, "D, M j")


class Role(models.Model):
    name = models.CharField(max_length=80, unique=True)
    color = models.CharField(
        max_length=7,
        default="#5f633f",
        validators=[RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Use a color code like #5f633f.")],
        help_text="Color of the role's marker, like #5f633f (olive), #425b76 (slate) or #a75531 (terracotta).",
    )
    order = models.PositiveSmallIntegerField(default=0, help_text="Lower numbers are listed first.")

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class EventQuerySet(models.QuerySet):
    def upcoming(self, include_closed=False):
        """Events that still have a shift today or later, soonest first. Only open ones unless include_closed."""
        events = self if include_closed else self.filter(is_open=True)
        return (
            events.filter(shifts__date__gte=timezone.localdate())
            .annotate(first_day=Min("shifts__date"))
            .order_by("first_day", "pk")
        )


class Event(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True, help_text="Used in the sign-up link: /volunteer/<slug>/")
    intro = models.TextField(blank=True, help_text="A short welcome shown at the top of the sign-up.")
    location = models.CharField(max_length=200, blank=True)
    location_url = models.URLField("Map link", blank=True)
    check_in = models.TextField(
        "When volunteers arrive", blank=True,
        help_text="Shown after someone signs up and in their confirmation email.",
    )
    good_to_know = models.TextField(blank=True, help_text="One note per line, for example what to wear.")
    is_open = models.BooleanField("Sign-ups open", default=True, help_text="Untick to stop new sign-ups.")
    ask_shirt_size = models.BooleanField("Ask for T-shirt size", default=False)
    ask_emergency_contact = models.BooleanField("Ask for an emergency contact", default=True)
    age_statement = models.CharField(
        "Age statement", max_length=200, blank=True,
        default="I’m 18 or older, or I’ll volunteer with my parent or guardian on the same shift.",
        help_text="Volunteers must tick this. Leave it blank to skip.",
    )
    agreement_statement = models.CharField(
        "Agreement", max_length=200, blank=True,
        default="I’ll follow the volunteer guidelines and directions from staff on site.",
        help_text="Volunteers must tick this. Leave it blank to skip.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def notes(self):
        return [line.strip() for line in self.good_to_know.splitlines() if line.strip()]

    @property
    def days(self):
        return sorted({s.date for s in self.shifts.all()})

    def date_range_text(self):
        days = self.days
        if not days:
            return ""
        first, last = days[0], days[-1]
        if len(days) == 1:
            return f"{long_day(first)}, {first.year}"
        joiner = "and" if len(days) == 2 else "to"
        return f"{long_day(first)} {joiner} {long_day(last)}, {last.year}"


class ShiftQuerySet(models.QuerySet):
    def with_taken(self):
        return self.annotate(taken=Count("assignments", filter=Q(assignments__cancelled=False)))


class Shift(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="shifts")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="shifts")
    date = models.DateField()
    start = models.TimeField()
    end = models.TimeField(help_text="If the shift runs past midnight, it ends on the next day.")
    capacity = models.PositiveSmallIntegerField("Volunteers needed", validators=[MinValueValidator(1)])
    where = models.CharField("Where on site", max_length=120, blank=True)
    details = models.TextField("What they'll do", blank=True)
    tags = models.CharField(
        max_length=200, blank=True,
        help_text="Short notes separated by commas, for example: Lifting up to 30 lb, Outdoors",
    )

    objects = ShiftQuerySet.as_manager()

    class Meta:
        ordering = ["date", "start", "role__order", "role__name"]

    def __str__(self):
        return f"{self.role}, {short_day(self.date)} at {clock(self.start)}"

    @property
    def starts_at(self):
        return datetime.combine(self.date, self.start, tzinfo=event_zone())

    @property
    def ends_at(self):
        day = self.date + timedelta(days=1) if self.end <= self.start else self.date
        return datetime.combine(day, self.end, tzinfo=event_zone())

    @property
    def minutes(self):
        return int((self.ends_at - self.starts_at).total_seconds() // 60)

    def overlaps(self, other):
        return self.starts_at < other.ends_at and other.starts_at < self.ends_at

    def has_started(self, now=None):
        return (now or timezone.now()) >= self.starts_at

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    @property
    def duration_text(self):
        hours, mins = divmod(self.minutes, 60)
        if not mins:
            return f"{hours} hour{'s' if hours != 1 else ''}"
        if mins == 30 and hours:
            return f"{hours}.5 hours"
        return f"{hours} hr {mins} min" if hours else f"{mins} min"

    @property
    def time_range(self):
        return f"{clock(self.start)} to {clock(self.end)}"

    @property
    def long_label(self):
        where = f" ({self.where})" if self.where else ""
        return f"{long_day(self.date)}, {self.time_range}: {self.role.name}{where}"


class Signup(models.Model):
    SHIRT_SIZES = [
        ("XS", "XS"), ("S", "S"), ("M", "M"), ("L", "L"), ("XL", "XL"), ("2XL", "2XL"), ("3XL", "3XL"),
        ("none", "No shirt, thanks"),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="signups")
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    email = models.EmailField()
    phone = models.CharField("Mobile phone", max_length=40)
    shirt_size = models.CharField("T-shirt size", max_length=8, choices=SHIRT_SIZES, blank=True)
    emergency_name = models.CharField("Emergency contact", max_length=120, blank=True)
    emergency_phone = models.CharField("Emergency contact phone", max_length=40, blank=True)
    notes = models.TextField("Anything we should know", blank=True)
    age_confirmed = models.BooleanField(default=False)
    agreed = models.BooleanField("Agreed to guidelines", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    shifts = models.ManyToManyField(Shift, through="Assignment", related_name="signups")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "volunteer sign-up"

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def active_shifts(self):
        return [a.shift for a in self.assignments.select_related("shift__role").filter(cancelled=False)]


class Assignment(models.Model):
    """One volunteer on one shift."""

    signup = models.ForeignKey(Signup, on_delete=models.CASCADE, related_name="assignments")
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name="assignments")
    cancelled = models.BooleanField(default=False, help_text="Tick to free up this spot.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["shift__date", "shift__start"]
        constraints = [models.UniqueConstraint(fields=["signup", "shift"], name="one_assignment_per_signup_shift")]
        verbose_name = "shift assignment"

    def __str__(self):
        return f"{self.signup} on {self.shift}"
