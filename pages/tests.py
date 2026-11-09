import json
import tempfile
from pathlib import Path
from unittest import mock

from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.urls import reverse


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
