import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Count, Min, Q
from django.utils import dateformat, timezone
from django.utils.text import capfirst
from django.utils.translation import get_language, gettext, ngettext, pgettext
from django.utils.translation import gettext_lazy as _


def event_zone():
    return ZoneInfo(settings.TIME_ZONE)


# Dates and times follow the visitor's language. The patterns are Django date formats
# (https://docs.djangoproject.com/en/5.2/ref/templates/builtins/#date), translated in locale/.

def clock(t):
    """9:00 AM in English, 9:00 a.m. in Spanish, the same on every operating system."""
    return dateformat.time_format(t, pgettext("time format", "g:i A"))


def _day(d):
    """Wednesday, November 25 (miércoles 25 de noviembre), without a capital for use mid-sentence."""
    return dateformat.format(d, pgettext("date format", "l, F j"))


def long_day(d):
    return capfirst(_day(d))


def short_day(d):
    return capfirst(dateformat.format(d, pgettext("date format", "D, M j")))


class Localized:
    """An object's text in the visitor's language: obj.local.name.

    It gives the Spanish version of a field (name_es for name) when the page is in Spanish and
    the Spanish box was filled in, and the English text otherwise.
    """

    def __init__(self, obj):
        self._obj = obj

    def __getattr__(self, field):
        if field.startswith("_"):
            raise AttributeError(field)
        value = getattr(self._obj, field)
        language = (get_language() or settings.LANGUAGE_CODE).split("-")[0]
        if language != settings.LANGUAGE_CODE:
            translated = getattr(self._obj, f"{field}_{language}", None)
            if isinstance(translated, str) and translated.strip():
                return translated
        return value


class Bilingual:
    """For models with Spanish versions of their text fields."""

    @property
    def local(self):
        return Localized(self)


class Role(Bilingual, models.Model):
    name = models.CharField(_("name"), max_length=80, unique=True)
    name_es = models.CharField(_("name in Spanish"), max_length=80, blank=True)
    color = models.CharField(
        _("color"),
        max_length=7,
        default="#5f633f",
        validators=[RegexValidator(r"^#[0-9A-Fa-f]{6}$", _("Use a color code like #5f633f."))],
        help_text=_("Color of the role’s marker, like #5f633f (olive), #425b76 (slate) or #a75531 (terracotta)."),
    )
    order = models.PositiveSmallIntegerField(_("order"), default=0, help_text=_("Lower numbers are listed first."))

    class Meta:
        ordering = ["order", "name"]
        verbose_name = _("role")
        verbose_name_plural = _("roles")

    def __str__(self):
        return self.local.name


class EventQuerySet(models.QuerySet):
    def upcoming(self, include_closed=False):
        """Events that still have a shift today or later, soonest first. Only open ones unless include_closed."""
        events = self if include_closed else self.filter(is_open=True)
        return (
            events.filter(shifts__date__gte=timezone.localdate())
            .annotate(first_day=Min("shifts__date"))
            .order_by("first_day", "pk")
        )


SPANISH_HELP = _("Shown when the site is in Spanish. Leave it empty to show the English text.")


class Event(Bilingual, models.Model):
    name = models.CharField(_("name"), max_length=120)
    name_es = models.CharField(_("name in Spanish"), max_length=120, blank=True, help_text=SPANISH_HELP)
    slug = models.SlugField(_("slug"), unique=True, help_text=_("The last part of the sign-up link, after /volunteer/"))
    intro = models.TextField(_("intro"), blank=True, help_text=_("A short welcome shown at the top of the sign-up."))
    intro_es = models.TextField(_("intro in Spanish"), blank=True, help_text=SPANISH_HELP)
    location = models.CharField(_("location"), max_length=200, blank=True)
    location_es = models.CharField(_("location in Spanish"), max_length=200, blank=True, help_text=SPANISH_HELP)
    location_url = models.URLField(_("Map link"), blank=True)
    check_in = models.TextField(
        _("When volunteers arrive"), blank=True,
        help_text=_("Shown after someone signs up and in their confirmation email."),
    )
    check_in_es = models.TextField(_("When volunteers arrive, in Spanish"), blank=True, help_text=SPANISH_HELP)
    good_to_know = models.TextField(
        _("good to know"), blank=True, help_text=_("One note per line, for example what to wear."),
    )
    good_to_know_es = models.TextField(
        _("good to know, in Spanish"), blank=True,
        help_text=_("One note per line, in the same order as the English. Leave it empty to show the English notes."),
    )
    is_open = models.BooleanField(_("Sign-ups open"), default=True, help_text=_("Untick to stop new sign-ups."))
    ask_shirt_size = models.BooleanField(_("Ask for T-shirt size"), default=False)
    ask_emergency_contact = models.BooleanField(_("Ask for an emergency contact"), default=True)
    age_statement = models.CharField(
        _("Age statement"), max_length=200, blank=True,
        default="I’m 18 or older, or I’ll volunteer with my parent or guardian on the same shift.",
        help_text=_("Volunteers must tick this. Leave it blank to skip it in both languages."),
    )
    age_statement_es = models.CharField(
        _("Age statement in Spanish"), max_length=200, blank=True,
        default="Tengo 18 años o más, o haré el voluntariado con mi padre, madre o tutor en el mismo turno.",
        help_text=SPANISH_HELP,
    )
    agreement_statement = models.CharField(
        _("Agreement"), max_length=200, blank=True,
        default="I’ll follow the volunteer guidelines and directions from staff on site.",
        help_text=_("Volunteers must tick this. Leave it blank to skip it in both languages."),
    )
    agreement_statement_es = models.CharField(
        _("Agreement in Spanish"), max_length=200, blank=True,
        default="Seguiré las pautas para voluntarios y las indicaciones del personal en el lugar.",
        help_text=SPANISH_HELP,
    )
    created_at = models.DateTimeField(_("created"), auto_now_add=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("event")
        verbose_name_plural = _("events")

    def __str__(self):
        return self.local.name

    @property
    def notes(self):
        return [line.strip() for line in self.local.good_to_know.splitlines() if line.strip()]

    @property
    def days(self):
        return sorted({s.date for s in self.shifts.all()})

    def date_range_text(self):
        days = self.days
        if not days:
            return ""
        first, last = days[0], days[-1]
        if len(days) == 1:
            text = gettext("%(day)s, %(year)s") % {"day": _day(first), "year": first.year}
        elif len(days) == 2:
            text = gettext("%(first)s and %(last)s, %(year)s") % {
                "first": _day(first), "last": _day(last), "year": last.year}
        else:
            text = gettext("%(first)s to %(last)s, %(year)s") % {
                "first": _day(first), "last": _day(last), "year": last.year}
        return capfirst(text)


class ShiftQuerySet(models.QuerySet):
    def with_taken(self):
        return self.annotate(taken=Count("assignments", filter=Q(assignments__cancelled=False)))


class Shift(Bilingual, models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="shifts", verbose_name=_("event"))
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="shifts", verbose_name=_("role"))
    date = models.DateField(_("date"))
    start = models.TimeField(_("start"))
    end = models.TimeField(_("end"), help_text=_("If the shift runs past midnight, it ends on the next day."))
    capacity = models.PositiveSmallIntegerField(_("Volunteers needed"), validators=[MinValueValidator(1)])
    where = models.CharField(_("Where on site"), max_length=120, blank=True)
    where_es = models.CharField(_("Where on site, in Spanish"), max_length=120, blank=True)
    details = models.TextField(_("What they’ll do"), blank=True)
    details_es = models.TextField(_("What they’ll do, in Spanish"), blank=True)
    tags = models.CharField(
        _("tags"), max_length=200, blank=True,
        help_text=_("Short notes separated by commas, for example: Lifting up to 30 lb, Outdoors"),
    )
    tags_es = models.CharField(
        _("tags in Spanish"), max_length=200, blank=True,
        help_text=_("The same notes in Spanish, separated by commas."),
    )

    objects = ShiftQuerySet.as_manager()

    class Meta:
        ordering = ["date", "start", "role__order", "role__name"]
        verbose_name = _("shift")
        verbose_name_plural = _("shifts")

    def __str__(self):
        return gettext("%(role)s, %(day)s at %(time)s") % {
            "role": self.role.local.name, "day": short_day(self.date), "time": clock(self.start)}

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
        return [t.strip() for t in self.local.tags.split(",") if t.strip()]

    @property
    def duration_text(self):
        hours, mins = divmod(self.minutes, 60)
        if not mins:
            return ngettext("%(hours)s hour", "%(hours)s hours", hours) % {"hours": hours}
        if mins == 30 and hours:
            # Translators: an hour and a half or more, like "2.5 hours".
            return ngettext("%(hours)s.5 hours", "%(hours)s.5 hours", hours) % {"hours": hours}
        if hours:
            return gettext("%(hours)s hr %(minutes)s min") % {"hours": hours, "minutes": mins}
        return gettext("%(minutes)s min") % {"minutes": mins}

    @property
    def day_text(self):
        return long_day(self.date)

    @property
    def short_day_text(self):
        return short_day(self.date)

    @property
    def start_text(self):
        return clock(self.start)

    @property
    def end_text(self):
        return clock(self.end)

    @property
    def time_range(self):
        return gettext("%(start)s to %(end)s") % {"start": clock(self.start), "end": clock(self.end)}

    @property
    def long_label(self):
        label = gettext("%(day)s, %(time)s: %(role)s") % {
            "day": long_day(self.date), "time": self.time_range, "role": self.role.local.name}
        where = self.local.where
        return f"{label} ({where})" if where else label


def default_language():
    return settings.LANGUAGE_CODE


class Signup(models.Model):
    SHIRT_SIZES = [
        ("XS", "XS"), ("S", "S"), ("M", "M"), ("L", "L"), ("XL", "XL"), ("2XL", "2XL"), ("3XL", "3XL"),
        ("none", _("No shirt, thanks")),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="signups", verbose_name=_("event"))
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    first_name = models.CharField(_("first name"), max_length=80)
    last_name = models.CharField(_("last name"), max_length=80)
    email = models.EmailField(_("email"))
    phone = models.CharField(_("Mobile phone"), max_length=40)
    shirt_size = models.CharField(_("T-shirt size"), max_length=8, choices=SHIRT_SIZES, blank=True)
    emergency_name = models.CharField(_("Emergency contact"), max_length=120, blank=True)
    emergency_phone = models.CharField(_("Emergency contact phone"), max_length=40, blank=True)
    notes = models.TextField(_("Anything we should know"), blank=True)
    age_confirmed = models.BooleanField(_("age confirmed"), default=False)
    agreed = models.BooleanField(_("Agreed to guidelines"), default=False)
    language = models.CharField(
        _("language"), max_length=8, choices=settings.LANGUAGES, default=default_language,
        help_text=_("The language they signed up in. Their confirmation email is in it too."),
    )
    created_at = models.DateTimeField(_("signed up"), auto_now_add=True)
    shifts = models.ManyToManyField(Shift, through="Assignment", related_name="signups", verbose_name=_("shifts"))

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("volunteer sign-up")
        verbose_name_plural = _("volunteer sign-ups")

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def active_shifts(self):
        return [a.shift for a in self.assignments.select_related("shift__role").filter(cancelled=False)]


class Assignment(models.Model):
    """One volunteer on one shift."""

    signup = models.ForeignKey(Signup, on_delete=models.CASCADE, related_name="assignments", verbose_name=_("volunteer"))
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name="assignments", verbose_name=_("shift"))
    cancelled = models.BooleanField(_("cancelled"), default=False, help_text=_("Tick to free up this spot."))
    created_at = models.DateTimeField(_("signed up"), auto_now_add=True)

    class Meta:
        ordering = ["shift__date", "shift__start"]
        constraints = [models.UniqueConstraint(fields=["signup", "shift"], name="one_assignment_per_signup_shift")]
        verbose_name = _("shift assignment")
        verbose_name_plural = _("shift assignments")

    def __str__(self):
        return gettext("%(volunteer)s on %(shift)s") % {"volunteer": self.signup, "shift": self.shift}
