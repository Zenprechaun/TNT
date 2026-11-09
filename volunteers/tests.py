from datetime import date, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from . import services
from .models import Assignment, Event, Role, Shift, Signup

JSON = {"HTTP_ACCEPT": "application/json"}


def clear_sample_event():
    """Remove the sample event and roles that migration 0002 adds, so each test starts empty."""
    Event.objects.all().delete()
    Role.objects.all().delete()


@override_settings(VOLUNTEER_SEND_CONFIRMATION=True, VOLUNTEER_NOTIFY_EMAILS=["boss@example.org"])
class SignupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        clear_sample_event()
        cls.kitchen = Role.objects.create(name="Kitchen crew", color="#5f633f", order=1)
        cls.serving = Role.objects.create(name="Serving line", color="#a75531", order=2)
        cls.event = Event.objects.create(name="Community Dinner", slug="dinner", location="Town hall",
                                         check_in="Check in at the table.")
        day = timezone.localdate() + timedelta(days=10)
        cls.morning = Shift.objects.create(event=cls.event, role=cls.kitchen, date=day, start=time(8), end=time(11), capacity=2)
        cls.midday = Shift.objects.create(event=cls.event, role=cls.serving, date=day, start=time(11), end=time(14), capacity=5)
        cls.overlap = Shift.objects.create(event=cls.event, role=cls.serving, date=day, start=time(10), end=time(12), capacity=5)
        cls.url = reverse("volunteers:signup", args=["dinner"])

    def data(self, *shifts, **extra):
        d = {"first_name": "Maya", "last_name": "Okafor", "email": "maya@example.com", "phone": "(530) 555-0142",
             "age_confirmed": "on", "agreed": "on", "shifts": [s.pk for s in shifts], "website": ""}
        d.update(extra)
        return d

    def post_json(self, data):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url, data, **JSON)

    def test_home_has_the_popup_and_the_volunteer_button(self):
        html = self.client.get("/").content.decode()
        self.assertIn('id="volunteer"', html)
        self.assertIn('href="/volunteer/" data-volunteer-open', html)
        self.assertIn("Community Dinner", html)
        self.assertEqual(html.count('name="shifts"'), 3)

    def test_start_goes_to_the_next_event(self):
        self.assertRedirects(self.client.get("/volunteer/"), self.url)

    def test_signup_by_popup(self):
        r = self.post_json(self.data(self.morning, self.midday))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["confirmation"]["firstName"], "Maya")
        self.assertEqual([s["id"] for s in body["confirmation"]["shifts"]], [self.morning.pk, self.midday.pk])
        self.assertEqual(body["counts"][str(self.morning.pk)], 1)
        signup = Signup.objects.get()
        self.assertTrue(signup.age_confirmed and signup.agreed)
        self.assertEqual(signup.assignments.count(), 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ["maya@example.com"])
        self.assertIn("Kitchen crew", mail.outbox[0].body)
        self.assertIn("Check in at the table.", mail.outbox[0].body)
        self.assertEqual(mail.outbox[1].to, ["boss@example.org"])

    def test_signup_without_javascript(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.url, self.data(self.morning))
        signup = Signup.objects.get()
        self.assertRedirects(r, reverse("volunteers:confirmed", args=["dinner", signup.token]))
        page = self.client.get(r["Location"]).content.decode()
        self.assertIn("Your shift is confirmed, Maya.", page)
        self.assertIn("calendar.google.com", page)

    def test_calendar_file(self):
        shift = Shift.objects.create(event=self.event, role=self.kitchen, date=date(2030, 1, 15),
                                     start=time(9), end=time(12), capacity=3)
        self.post_json(self.data(shift))
        signup = Signup.objects.get()
        r = self.client.get(reverse("volunteers:calendar", args=["dinner", signup.token]))
        ics = r.content.decode()
        self.assertEqual(r["Content-Type"], "text/calendar; charset=utf-8")
        self.assertIn("DTSTART:20300115T170000Z", ics)  # 9 AM Pacific in January
        self.assertIn("DTEND:20300115T200000Z", ics)
        self.assertTrue(all(len(line.encode()) <= 75 for line in ics.split("\r\n")))

    def test_overlapping_shifts_are_refused(self):
        r = self.post_json(self.data(self.morning, self.overlap))
        self.assertEqual(r.status_code, 400)
        self.assertIn("overlap", r.json()["errors"]["shifts"][0])
        self.assertFalse(Signup.objects.exists())

    def test_back_to_back_shifts_are_fine(self):
        self.assertEqual(self.post_json(self.data(self.morning, self.midday)).status_code, 200)

    def test_full_shift_is_refused_and_nothing_is_saved(self):
        self.post_json(self.data(self.morning, email="a@example.com"))
        self.post_json(self.data(self.morning, email="b@example.com"))
        r = self.post_json(self.data(self.morning, self.midday, email="c@example.com"))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["remove"], [self.morning.pk])
        self.assertIn("filled up", r.json()["message"])
        self.assertFalse(Signup.objects.filter(email="c@example.com").exists())
        self.assertEqual(self.midday.assignments.count(), 0)

    def test_cancelled_spot_opens_up(self):
        self.post_json(self.data(self.morning, email="a@example.com"))
        self.post_json(self.data(self.morning, email="b@example.com"))
        Assignment.objects.filter(signup__email="a@example.com").update(cancelled=True)
        self.assertEqual(self.post_json(self.data(self.morning, email="c@example.com")).status_code, 200)

    def test_same_email_cannot_take_a_shift_twice(self):
        self.post_json(self.data(self.morning))
        r = self.post_json(self.data(self.morning, email="MAYA@example.com"))
        self.assertEqual(r.status_code, 409)
        self.assertIn("already signed up", r.json()["message"])
        self.assertEqual(self.morning.assignments.count(), 1)

    def test_missing_details(self):
        r = self.post_json({"shifts": [self.morning.pk], "phone": "123"})
        self.assertEqual(r.status_code, 400)
        errors = r.json()["errors"]
        self.assertEqual(errors["first_name"], ["Enter your first name."])
        self.assertEqual(errors["email"], ["Enter your email address."])
        self.assertEqual(errors["phone"], ["Enter a phone number with its area code."])
        self.assertIn("age_confirmed", errors)
        self.assertIn("agreed", errors)

    def test_no_shift_chosen(self):
        r = self.post_json(self.data())
        self.assertEqual(r.json()["errors"]["shifts"], ["Choose at least one shift."])

    def test_page_shows_errors_without_javascript(self):
        r = self.client.post(self.url, self.data(self.morning, email="nope"))
        self.assertContains(r, "Enter an email address like name@example.com.")
        self.assertContains(r, 'aria-invalid="true"')

    def test_spam_trap(self):
        r = self.post_json(self.data(self.morning, website="http://spam.example"))
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Signup.objects.exists())

    def test_started_shift_cannot_be_chosen(self):
        past = Shift.objects.create(event=self.event, role=self.kitchen, date=timezone.localdate() - timedelta(days=1),
                                    start=time(8), end=time(9), capacity=3)
        r = self.post_json(self.data(past))
        self.assertIn("already started", r.json()["errors"]["shifts"][0])

    def test_closed_event(self):
        Event.objects.filter(pk=self.event.pk).update(is_open=False)
        r = self.post_json(self.data(self.morning))
        self.assertEqual(r.json()["error"], "closed")
        self.assertContains(self.client.get(self.url), "Sign-ups for Community Dinner are closed.")
        self.assertContains(self.client.get("/volunteer/"), "There are no volunteer shifts open right now.")
        self.assertContains(self.client.get("/"), "There are no volunteer shifts open right now.")

    def test_spots(self):
        self.post_json(self.data(self.morning))
        counts = self.client.get(reverse("volunteers:spots", args=["dinner"])).json()["counts"]
        self.assertEqual(counts[str(self.morning.pk)], 1)
        self.assertEqual(counts[str(self.midday.pk)], 0)

    def test_unknown_token(self):
        r = self.client.get(reverse("volunteers:confirmed", args=["dinner", "00000000-0000-0000-0000-000000000000"]))
        self.assertEqual(r.status_code, 404)


class AdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        clear_sample_event()
        cls.admin = get_user_model().objects.create_superuser("organizer", "o@example.org", "a-long-test-password")
        role = Role.objects.create(name="Setup crew")
        cls.event = Event.objects.create(name="Dinner", slug="dinner")
        cls.shift = Shift.objects.create(event=cls.event, role=role, date=timezone.localdate() + timedelta(days=3),
                                         start=time(9), end=time(12), capacity=4)
        signup = Signup.objects.create(event=cls.event, first_name="=HYPERLINK(1)", last_name="Lee",
                                       email="lee@example.com", phone="+1 530 555 0100")
        Assignment.objects.create(signup=signup, shift=cls.shift)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_pages_load(self):
        for name, args in [("admin:volunteers_event_changelist", []), ("admin:volunteers_event_change", [self.event.pk]),
                           ("admin:volunteers_shift_changelist", []), ("admin:volunteers_shift_change", [self.shift.pk]),
                           ("admin:volunteers_signup_changelist", []), ("admin:volunteers_role_changelist", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)

    def test_roster_download(self):
        r = self.client.post(reverse("admin:volunteers_shift_changelist"),
                             {"action": "download_roster", "_selected_action": [self.shift.pk]})
        text = r.content.decode("utf-8-sig")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("'=HYPERLINK(1)", text)
        self.assertIn("'+1 530 555 0100", text)
        self.assertIn("Setup crew", text)
        self.assertIn("Language", text.splitlines()[0])
        self.assertIn("English", text)


class SampleEventTests(TestCase):
    def test_migration_adds_the_sample_event_closed(self):
        event = Event.objects.get(slug="community-thanksgiving-2026")
        self.assertFalse(event.is_open)
        self.assertEqual(event.shifts.count(), 8)

    def test_the_sample_event_has_spanish_text(self):
        event = Event.objects.get(slug="community-thanksgiving-2026")
        self.assertEqual(event.name_es, "Día de Acción de Gracias Comunitario de Tahoe")
        self.assertTrue(event.intro_es and event.check_in_es and event.age_statement_es)
        self.assertEqual(len(event.good_to_know_es.splitlines()), len(event.good_to_know.splitlines()))
        self.assertFalse(Role.objects.filter(name_es="").exists())
        for shift in event.shifts.all():
            self.assertTrue(shift.where_es and shift.details_es, shift)
            self.assertEqual(bool(shift.tags), bool(shift.tags_es), shift)
        greeters = event.shifts.get(role__name="Greeters and check-in")
        self.assertEqual(greeters.tags_es, "Ideal si habla español")


class AdminPreviewTests(TestCase):
    """Before sign-ups open, admins can see and try the sign-up. Nobody else sees it, and nothing is saved."""

    @classmethod
    def setUpTestData(cls):
        clear_sample_event()
        cls.admin = get_user_model().objects.create_superuser("organizer", "o@example.org", "a-long-test-password")
        role = Role.objects.create(name="Kitchen crew")
        cls.event = Event.objects.create(name="Winter Supper", slug="supper", is_open=False)
        cls.shift = Shift.objects.create(event=cls.event, role=role, date=timezone.localdate() + timedelta(days=5),
                                         start=time(16), end=time(19), capacity=6)
        cls.url = reverse("volunteers:signup", args=["supper"])

    def test_visitors_see_that_nothing_is_open(self):
        self.assertContains(self.client.get("/"), "There are no volunteer shifts open right now.")
        self.assertNotContains(self.client.get("/"), "Winter Supper")
        self.assertContains(self.client.get("/volunteer/"), "There are no volunteer shifts open right now.")
        self.assertContains(self.client.get(self.url), "Sign-ups for Winter Supper are closed.")

    def test_admins_get_a_preview_in_the_popup(self):
        self.client.force_login(self.admin)
        html = self.client.get("/").content.decode()
        self.assertIn("Winter Supper", html)
        self.assertIn("data-preview", html)
        self.assertIn("Admin preview.", html)
        self.assertIn(reverse("admin:volunteers_event_change", args=[self.event.pk]), html)

    def test_admins_get_a_preview_page(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get("/volunteer/"), self.url)
        page = self.client.get(self.url)
        self.assertContains(page, "Admin preview.")
        self.assertContains(page, "data-preview")

    def test_nothing_is_saved_from_a_preview(self):
        self.client.force_login(self.admin)
        data = {"first_name": "Ana", "last_name": "Ruiz", "email": "ana@example.com", "phone": "530 555 0199",
                "age_confirmed": "on", "agreed": "on", "shifts": [self.shift.pk], "website": ""}
        r = self.client.post(self.url, data, **JSON)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"], "closed")
        self.assertFalse(Signup.objects.exists())

    def test_open_events_are_not_previews(self):
        Event.objects.filter(pk=self.event.pk).update(is_open=True)
        self.client.force_login(self.admin)
        html = self.client.get("/").content.decode()
        self.assertIn("Winter Supper", html)
        self.assertNotIn("data-preview", html)
        self.assertNotIn("Admin preview.", html)


@override_settings(VOLUNTEER_SEND_CONFIRMATION=True, VOLUNTEER_NOTIFY_EMAILS=["boss@example.org"])
class SpanishTests(TestCase):
    """With the site in Spanish, the sign-up is in Spanish too, including each event's own Spanish text."""

    @classmethod
    def setUpTestData(cls):
        clear_sample_event()
        cls.kitchen = Role.objects.create(name="Kitchen crew", name_es="Equipo de cocina", order=1)
        cls.serving = Role.objects.create(name="Serving line", order=2)  # no Spanish name yet
        cls.event = Event.objects.create(
            name="Community Dinner", name_es="Cena comunitaria", slug="dinner",
            location="Town hall", location_es="Centro comunitario",
            check_in="Check in at the table.", check_in_es="Regístrese en la mesa.",
            good_to_know="Wear closed-toe shoes.", good_to_know_es="Use zapatos cerrados.",
        )
        cls.day = date(2030, 11, 27)  # a Wednesday
        cls.morning = Shift.objects.create(event=cls.event, role=cls.kitchen, date=cls.day, start=time(8),
                                           end=time(10, 30), capacity=2, where="Kitchen", where_es="Cocina",
                                           tags="Closed-toe shoes", tags_es="Zapatos cerrados")
        cls.midday = Shift.objects.create(event=cls.event, role=cls.serving, date=cls.day, start=time(13),
                                          end=time(16), capacity=5, where="Dining hall")
        cls.url = reverse("volunteers:signup", args=["dinner"])

    def setUp(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "es"

    def data(self, *shifts, **extra):
        d = {"first_name": "Maya", "last_name": "Okafor", "email": "maya@example.com", "phone": "(530) 555-0142",
             "age_confirmed": "on", "agreed": "on", "shifts": [s.pk for s in shifts], "website": ""}
        d.update(extra)
        return d

    def post_json(self, data):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url, data, **JSON)

    def test_the_sign_up_is_in_spanish(self):
        html = self.client.get(self.url).content.decode()
        for text in ['<html lang="es">', "Cena comunitaria", "Centro comunitario", "Use zapatos cerrados.",
                     "Equipo de cocina", "Cocina", "Zapatos cerrados", "Miércoles 27 de noviembre de 2030",
                     "Miércoles 27 de noviembre", "8:00 a.m.", "a 10:30 a.m.", "2 horas y media", "3 horas",
                     'data-short-day="Mié 27 nov"', "Elija sus turnos", "Confirmar mis turnos",
                     "Tengo 18 años o más", "2 de 2 lugares libres"]:
            self.assertIn(text, html)
        self.assertNotIn("Community Dinner", html)

    def test_text_without_a_spanish_version_shows_in_english(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Serving line", html)
        self.assertIn("Dining hall", html)

    def test_english_is_unchanged(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        html = self.client.get(self.url).content.decode()
        for text in ['<html lang="en">', "Community Dinner", "Wednesday, November 27, 2030", "8:00 AM",
                     "to 10:30 AM", "2.5 hours", "Kitchen crew", "Choose your shifts", "2 of 2 spots left"]:
            self.assertIn(text, html)
        self.assertNotIn("Cena comunitaria", html)

    def test_signing_up_in_spanish(self):
        r = self.post_json(self.data(self.morning))
        self.assertEqual(r.status_code, 200)
        shift = r.json()["confirmation"]["shifts"][0]
        self.assertEqual(shift["day"], "Miércoles 27 de noviembre")
        self.assertEqual(shift["time"], "8:00 a.m. a 10:30 a.m.")
        self.assertEqual(shift["role"], "Equipo de cocina")
        self.assertEqual(shift["where"], "Cocina")
        self.assertEqual(Signup.objects.get().language, "es")

        volunteer, organizer = mail.outbox
        self.assertEqual(volunteer.subject, "Inscripción confirmada: Cena comunitaria")
        self.assertIn("Hola, Maya:", volunteer.body)
        self.assertIn("Miércoles 27 de noviembre, 8:00 a.m. a 10:30 a.m.: Equipo de cocina (Cocina)", volunteer.body)
        self.assertIn("Al llegar: Regístrese en la mesa.", volunteer.body)
        # Organizers read theirs in English, with the volunteer's language noted.
        self.assertEqual(organizer.subject, "New volunteer: Maya Okafor (Community Dinner)")
        self.assertIn("Language: Español", organizer.body)
        self.assertIn("Kitchen crew", organizer.body)

    def test_the_email_is_in_the_language_of_the_sign_up(self):
        signup = Signup.objects.create(event=self.event, first_name="Ana", last_name="Ruiz",
                                       email="ana@example.com", phone="530 555 0199", language="es")
        Assignment.objects.create(signup=signup, shift=self.morning)
        with translation.override("en"):
            services.send_emails(signup.pk)
        self.assertIn("Hola, Ana:", mail.outbox[0].body)

    def test_problems_are_explained_in_spanish(self):
        r = self.post_json({"shifts": [self.morning.pk], "phone": "123"})
        errors = r.json()["errors"]
        self.assertEqual(errors["first_name"], ["Escriba su nombre."])
        self.assertEqual(errors["phone"], ["Escriba un número de teléfono con su código de área."])
        overlap = Shift.objects.create(event=self.event, role=self.serving, date=self.day, start=time(9),
                                       end=time(12), capacity=3)
        r = self.post_json(self.data(self.morning, overlap))
        self.assertIn("se superponen", r.json()["errors"]["shifts"][0])

    def test_a_full_shift_is_explained_in_spanish(self):
        self.post_json(self.data(self.morning, email="a@example.com"))
        self.post_json(self.data(self.morning, email="b@example.com"))
        r = self.post_json(self.data(self.morning, email="c@example.com"))
        self.assertEqual(r.json()["title"], "Un turno ya no está disponible")
        self.assertIn("ya no quedó lugar en Equipo de cocina", r.json()["message"])

    def test_closed_in_spanish(self):
        Event.objects.filter(pk=self.event.pk).update(is_open=False)
        self.assertContains(self.client.get(self.url), "Las inscripciones para el evento Cena comunitaria están cerradas.")

    def test_calendar_in_spanish(self):
        self.post_json(self.data(self.morning))
        signup = Signup.objects.get()
        ics = self.client.get(reverse("volunteers:calendar", args=["dinner", signup.token])).content.decode()
        unfolded = ics.replace("\r\n ", "")
        self.assertIn("SUMMARY:Voluntariado: Equipo de cocina\\, Cena comunitaria", unfolded)
        self.assertIn("LOCATION:Centro comunitario", unfolded)

    def test_dates_and_lengths(self):
        thursday, friday = self.day + timedelta(days=1), self.day + timedelta(days=2)
        Shift.objects.create(event=self.event, role=self.kitchen, date=thursday, start=time(9), end=time(10),
                             capacity=1)
        cases = [
            ("en", "Wednesday, November 27 and Thursday, November 28, 2030", "1.5 hours", "1 hour", "1 hr 15 min"),
            ("es", "Miércoles 27 de noviembre y jueves 28 de noviembre de 2030", "1 hora y media", "1 hora",
             "1 h 15 min"),
        ]
        for language, two_days, ninety, sixty, seventy_five in cases:
            with translation.override(language):
                self.assertEqual(self.event.date_range_text(), two_days)
                lengths = [Shift(date=self.day, start=time(9), end=end).duration_text
                           for end in (time(10, 30), time(10), time(10, 15), time(9, 45))]
                self.assertEqual(lengths, [ninety, sixty, seventy_five, "45 min"])
        Shift.objects.create(event=self.event, role=self.kitchen, date=friday, start=time(9), end=time(10),
                             capacity=1)
        with translation.override("es"):
            self.assertEqual(self.event.date_range_text(),
                             "Del miércoles 27 de noviembre al viernes 29 de noviembre de 2030")
        with translation.override("en"):
            self.assertEqual(self.event.date_range_text(), "Wednesday, November 27 to Friday, November 29, 2030")
