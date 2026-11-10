from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.utils import translation

from emails.models import Email, EmailSettings
from emails.sending import current_connection, send


class Command(BaseCommand):
    help = "Sends a test email, to check that the site can send email. The Management page has the same button."

    def add_arguments(self, parser):
        parser.add_argument("to", help="the address to send it to")

    def handle(self, *args, to, **options):
        try:
            validate_email(to)
        except ValidationError:
            raise CommandError(f"{to} isn't an email address.")
        conf = EmailSettings.load()
        connection = current_connection(conf)
        if connection is None:
            raise CommandError("Email is off. Connect an email service on the Management page "
                               "(/dashboard/manage/#email) first.")
        with translation.override(settings.LANGUAGE_CODE):
            body = render_to_string("emails/email/test.txt", {"sender": None, "service": conf.service_name})
            record = send(Email.TEST, to, "Test email from Tahoe Neighborhood Table", body, ref="test", conf=conf)
            problem = str(record.problem_text)
        if record.status != Email.SENT:
            raise CommandError(f"The test email didn't go out. {problem} The email service said: {record.error}")
        self.stdout.write(f"Sent a test email to {to} through {connection.host}.")
