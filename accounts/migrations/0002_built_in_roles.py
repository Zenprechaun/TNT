"""Creates the built-in Admin and User roles, and gives any existing accounts a profile."""

from django.conf import settings
from django.db import migrations

ROLES = [
    ("admin", "Admin", "Uses the Admin's Dashboard and the full admin site, and manages people's roles."),
    ("user", "User", "Signs in and uses the User's Dashboard."),
]


def create_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for slug, name, description in ROLES:
        Role.objects.update_or_create(slug=slug, defaults={"name": name, "description": description})


def give_existing_accounts_profiles(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    Profile = apps.get_model("accounts", "Profile")
    Role = apps.get_model("accounts", "Role")
    user_role = Role.objects.get(slug="user")
    admin_role = Role.objects.get(slug="admin")
    for user in User.objects.all():
        profile, created = Profile.objects.get_or_create(user=user)
        if created:
            profile.roles.add(user_role)
            if user.is_superuser:
                profile.roles.add(admin_role)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(create_roles, migrations.RunPython.noop),
        migrations.RunPython(give_existing_accounts_profiles, migrations.RunPython.noop),
    ]
