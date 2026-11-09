from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Role
from .roles import get_profile

User = get_user_model()
PASSWORD = "a-long-test-password-123"


def make_person(username, *, admin=False, **extra):
    person = User.objects.create_user(username=username, password=PASSWORD, **extra)
    if admin:
        get_profile(person).roles.add(Role.objects.get(slug=Role.ADMIN))
        person.refresh_from_db()
    return person


class RoleTests(TestCase):
    def test_admin_and_user_roles_are_built_in(self):
        self.assertTrue({"admin", "user"} <= set(Role.objects.values_list("slug", flat=True)))

    def test_new_people_get_the_user_role(self):
        person = make_person("sam")
        self.assertEqual([role.slug for role in get_profile(person).roles.all()], ["user"])
        self.assertFalse(person.is_staff)

    def test_superusers_get_the_admin_role(self):
        boss = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.assertTrue(get_profile(boss).is_admin)

    def test_the_admin_role_controls_admin_site_access(self):
        person = make_person("alex", admin=True)
        self.assertTrue(person.is_staff and person.is_superuser)
        get_profile(person).roles.remove(Role.objects.get(slug=Role.ADMIN))
        person.refresh_from_db()
        self.assertFalse(person.is_staff or person.is_superuser)


class LoginTests(TestCase):
    def setUp(self):
        self.admin = make_person("Jordan", admin=True, email="jordan@example.com")
        self.person = make_person("casey", email="casey@example.com")
        self.url = reverse("accounts:login")

    def test_admins_are_taken_to_the_admin_dashboard(self):
        response = self.client.post(self.url, {"username": "Jordan", "password": PASSWORD})
        self.assertRedirects(response, reverse("accounts:admin_dashboard"))

    def test_everyone_else_is_taken_to_the_user_dashboard(self):
        response = self.client.post(self.url, {"username": "casey", "password": PASSWORD})
        self.assertRedirects(response, reverse("accounts:user_dashboard"))

    def test_the_popup_gets_the_dashboard_address_as_json(self):
        response = self.client.post(
            self.url, {"username": "Jordan", "password": PASSWORD}, headers={"accept": "application/json"}
        )
        self.assertEqual(response.json(), {"ok": True, "redirect": reverse("accounts:admin_dashboard")})

    def test_the_popup_gets_a_message_for_a_wrong_password(self):
        response = self.client.post(
            self.url, {"username": "casey", "password": "wrong"}, headers={"accept": "application/json"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn("isn't right", response.json()["message"])
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_email_or_username_in_any_letter_case_works(self):
        for identifier in ("casey@example.com", "CASEY@Example.com", "Casey"):
            self.client.logout()
            response = self.client.post(self.url, {"username": identifier, "password": PASSWORD})
            self.assertRedirects(response, reverse("accounts:user_dashboard"), msg_prefix=identifier)

    def test_keep_me_signed_in(self):
        self.client.post(self.url, {"username": "casey", "password": PASSWORD})
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.client.logout()
        self.client.post(self.url, {"username": "casey", "password": PASSWORD, "remember": "1"})
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_next_is_followed_only_within_the_site(self):
        response = self.client.post(
            self.url, {"username": "casey", "password": PASSWORD, "next": "https://elsewhere.example/"}
        )
        self.assertRedirects(response, reverse("accounts:user_dashboard"))
        self.client.logout()
        response = self.client.post(
            self.url, {"username": "Jordan", "password": PASSWORD, "next": reverse("accounts:user_dashboard")}
        )
        self.assertRedirects(response, reverse("accounts:user_dashboard"))

    def test_the_login_page_shows_the_problem(self):
        response = self.client.post(self.url, {"username": "casey", "password": "wrong"})
        self.assertContains(response, "isn&#x27;t right")

    def test_logging_out_needs_a_post(self):
        self.client.force_login(self.person)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("pages:home"))
        self.assertNotIn("_auth_user_id", self.client.session)


class DashboardAccessTests(TestCase):
    def setUp(self):
        self.admin = make_person("Jordan", admin=True)
        self.person = make_person("casey")

    def test_signed_out_visitors_are_sent_to_log_in(self):
        url = reverse("accounts:admin_dashboard")
        self.assertRedirects(self.client.get(url), f"{reverse('accounts:login')}?next={url}")

    def test_people_without_the_admin_role_cannot_open_the_admin_dashboard(self):
        self.client.force_login(self.person)
        response = self.client.get(reverse("accounts:admin_dashboard"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "needs a different role", status_code=403)

    def test_admins_can_open_both_dashboards(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("accounts:admin_dashboard")), "Admin's Dashboard")
        self.assertContains(self.client.get(reverse("accounts:user_dashboard")), "User's Dashboard")

    def test_the_dashboard_link_follows_roles(self):
        self.client.force_login(self.person)
        self.assertRedirects(self.client.get(reverse("accounts:dashboard")), reverse("accounts:user_dashboard"))

    def test_the_home_page_offers_log_in_until_signed_in(self):
        home = reverse("pages:home")
        response = self.client.get(home)
        self.assertContains(response, 'id="login-dialog"')
        self.assertContains(response, "data-login-open")
        self.client.force_login(self.person)
        response = self.client.get(home)
        self.assertNotContains(response, 'id="login-dialog"')
        self.assertContains(response, "Log out")


class RoleManagementTests(TestCase):
    def setUp(self):
        self.admin = make_person("Jordan", admin=True)
        self.person = make_person("casey")
        self.admin_role = Role.objects.get(slug=Role.ADMIN)
        self.user_role = Role.objects.get(slug=Role.USER)

    def roles_url(self, person):
        return reverse("accounts:update_roles", args=[person.pk])

    def test_admins_can_give_someone_the_admin_role(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.roles_url(self.person), {"roles": [self.admin_role.pk, self.user_role.pk]})
        self.assertRedirects(
            response,
            f"{reverse('accounts:admin_dashboard')}#person-{self.person.pk}",
            fetch_redirect_response=False,
        )
        self.person.refresh_from_db()
        self.assertTrue(get_profile(self.person).is_admin)
        self.assertTrue(self.person.is_staff)

    def test_admins_cannot_remove_their_own_admin_role(self):
        self.client.force_login(self.admin)
        self.client.post(self.roles_url(self.admin), {"roles": [self.user_role.pk]})
        self.assertTrue(get_profile(self.admin).is_admin)

    def test_at_least_one_role_is_required(self):
        self.client.force_login(self.admin)
        self.client.post(self.roles_url(self.person), {})
        self.assertEqual(list(get_profile(self.person).roles.values_list("slug", flat=True)), ["user"])

    def test_people_without_the_admin_role_cannot_change_roles(self):
        self.client.force_login(self.person)
        response = self.client.post(self.roles_url(self.person), {"roles": [self.admin_role.pk]})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_profile(self.person).is_admin)
