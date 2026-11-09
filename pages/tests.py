import gettext
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from . import translation_files
from .translation_files import Message, compile_mo, default_header, format_po, parse_po, problems_in


class HomePageTests(TestCase):
    def test_home_page_loads(self):
        response = self.client.get(reverse("pages:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Log in")


class HealthCheckTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.status_file = Path(folder.name) / "publish-status.json"
        overrides = override_settings(PUBLISH_STATUS_FILE=self.status_file, SITE_REVISION="abc123")
        overrides.enable()
        self.addCleanup(overrides.disable)

    def get(self):
        return self.client.get(reverse("pages:healthz"))

    def test_reports_status_and_revision(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "database": "ok", "revision": "abc123", "publish": None},
        )

    def test_is_never_cached(self):
        self.assertIn("no-store", self.get()["Cache-Control"])

    def test_includes_the_latest_publish_with_known_fields_only(self):
        self.status_file.write_text(
            json.dumps(
                {
                    "revision": "abc123",
                    "state": "ok",
                    "step": "done",
                    "message": "The website is running this version.",
                    "finished_at": "2026-11-09T04:00:00+00:00",
                    "extra": "not shown",
                }
            )
        )
        self.assertEqual(
            self.get().json()["publish"],
            {
                "revision": "abc123",
                "state": "ok",
                "step": "done",
                "message": "The website is running this version.",
                "finished_at": "2026-11-09T04:00:00+00:00",
            },
        )

    def test_ignores_a_status_file_it_cannot_read(self):
        self.status_file.write_text("not json")
        self.assertIsNone(self.get().json()["publish"])
        self.status_file.write_text("[1, 2]")
        self.assertIsNone(self.get().json()["publish"])

    def test_only_answers_get(self):
        self.assertEqual(self.client.post(reverse("pages:healthz")).status_code, 405)

    def test_reports_a_database_problem(self):
        with mock.patch("pages.views.connection.cursor", side_effect=DatabaseError("down")):
            response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "error")
        self.assertEqual(response.json()["database"], "unavailable")


class LanguageTests(TestCase):
    def test_english_by_default(self):
        response = self.client.get("/")
        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, "Outreach to those in need of")
        self.assertContains(response, 'value="en" lang="en" title="English" aria-pressed="true"')

    def test_spanish_browsers_get_spanish(self):
        response = self.client.get("/", headers={"accept-language": "es-MX,es;q=0.9,en;q=0.5"})
        self.assertContains(response, '<html lang="es">')
        self.assertContains(response, "Apoyo para quienes necesitan")
        self.assertContains(response, "Creemos que todos merecen")
        self.assertContains(response, 'value="es" lang="es" title="Español" aria-pressed="true"')
        self.assertNotContains(response, "Outreach to those in need of")

    def test_the_switch_remembers_the_choice(self):
        response = self.client.post(reverse("set_language"), {"language": "es", "next": "/volunteer/"})
        self.assertRedirects(response, "/volunteer/", fetch_redirect_response=False)
        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, "es")
        # The choice wins over the browser's language until it's switched back.
        self.assertContains(self.client.get("/", headers={"accept-language": "en"}), "Apoyo para quienes necesitan")
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        self.assertContains(self.client.get("/"), "Outreach to those in need of")

    def test_the_switch_only_returns_to_this_site(self):
        response = self.client.post(reverse("set_language"), {"language": "es", "next": "https://elsewhere.example/"})
        self.assertEqual(response["Location"], "/")

    def test_the_switch_is_on_every_page(self):
        for url in ["/", reverse("accounts:login"), "/volunteer/", "/no-such-page/"]:
            response = self.client.get(url, follow=True)
            self.assertContains(response, 'class="lang-switch', status_code=response.status_code, msg_prefix=url)

    def test_scripts_get_their_text_in_spanish(self):
        response = self.client.get(reverse("javascript-catalog"), headers={"accept-language": "es"})
        self.assertContains(response, "Confirmar mis turnos")
        self.assertNotContains(response, "Available %s")  # the admin's own script text isn't sent

    def test_the_login_problem_is_explained_in_spanish(self):
        response = self.client.post(reverse("accounts:login"), {"username": "nobody", "password": "wrong"},
                                    headers={"accept": "application/json", "accept-language": "es"})
        self.assertIn("no son correctos", response.json()["message"])


class TranslationFileTests(SimpleTestCase):
    def test_every_piece_of_text_has_a_spanish_translation(self):
        """Fails when text was added or changed without updating locale/es. The message says what to run."""
        problems = translation_files.status()
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_finds_text_in_templates_python_and_scripts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for sub in ("app/templates", "app/static", "app/migrations"):
                (root / sub).mkdir(parents=True)
            (root / "app/templates/page.html").write_text(
                '{% load i18n %}<h1>{% translate "Hello" %}</h1>'
                "{% blocktranslate trimmed count n=items|length %}{{ n }} item{% plural %}{{ n }} items"
                "{% endblocktranslate %}{% translate \"May\" context \"month\" %}")
            (root / "app/views.py").write_text(
                "from django.utils.translation import gettext as _, ngettext\n"
                "# Translators: on the button.\n"
                "LABEL = _(\"Save\")\n"
                "def label(n):\n"
                "    return ngettext(\"%(n)s shift\", \"%(n)s shifts\", n)\n")
            (root / "app/static/app.js").write_text("gettext('Copied'); ngettext('%s spot', '%s spots', n);")
            (root / "app/migrations/0001_initial.py").write_text("_(\"Not this\")")
            found = translation_files.extract(root)
        self.assertEqual(
            {(m.context, m.msgid, m.plural) for m in found["django"]},
            {(None, "Hello", None), (None, "%(n)s item", "%(n)s items"), ("month", "May", None),
             (None, "Save", None), (None, "%(n)s shift", "%(n)s shifts")})
        save = next(m for m in found["django"] if m.msgid == "Save")
        self.assertEqual(save.notes, ["Translators: on the button."])
        self.assertEqual({(m.msgid, m.plural) for m in found["djangojs"]}, {("Copied", None), ("%s spot", "%s spots")})

    def test_text_to_translate_must_be_written_out(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "views.py").write_text("from django.utils.translation import gettext\ngettext(name)\n")
            with self.assertRaises(translation_files.ExtractError):
                translation_files.extract(folder)

    def sample(self):
        return [
            Message(msgid='Say "hi"\nnow', msgstr='Diga "hola"\nahora', locations=["a.html"]),
            Message(msgid="%s shift", plural="%s shifts", msgstr_plural={0: "%s turno", 1: "%s turnos"},
                    flags={"python-format"}),
            Message(msgid="May", context="month", msgstr="mayo"),
            Message(msgid="Untranslated"),
            Message(msgid="Old", msgstr="Viejo", obsolete=True),
        ]

    def test_po_files_read_back_the_same(self):
        text = format_po(["# A test file."], default_header("es"), self.sample())
        head, header, messages = parse_po(text)
        self.assertEqual(format_po(head, header, messages), text)
        self.assertEqual([(m.msgid, m.msgstr, m.msgstr_plural, m.context, m.obsolete) for m in messages],
                         [(m.msgid, m.msgstr, m.msgstr_plural, m.context, m.obsolete) for m in self.sample()])

    def test_compiled_files_work_with_gettext(self):
        catalog = gettext.GNUTranslations(io.BytesIO(compile_mo(default_header("es"), self.sample())))
        self.assertEqual(catalog.gettext('Say "hi"\nnow'), 'Diga "hola"\nahora')
        self.assertEqual(catalog.ngettext("%s shift", "%s shifts", 1), "%s turno")
        self.assertEqual(catalog.ngettext("%s shift", "%s shifts", 3), "%s turnos")
        self.assertEqual(catalog.pgettext("month", "May"), "mayo")
        self.assertEqual(catalog.gettext("Untranslated"), "Untranslated")
        self.assertEqual(catalog.gettext("Old"), "Old")

    def test_catches_translations_that_would_break_the_page(self):
        self.assertTrue(problems_in(Message(msgid="Hi %(name)s", msgstr="Hola %(nombre)s"), 2))
        self.assertTrue(problems_in(Message(msgid='Email <a href="%(url)s">us</a>', msgstr="Escríbanos %(url)s"), 2))
        self.assertTrue(problems_in(Message(msgid="%s left", msgstr="quedan"), 2))
        self.assertFalse(problems_in(Message(msgid="Hi %(name)s", msgstr="Hola, %(name)s"), 2))
