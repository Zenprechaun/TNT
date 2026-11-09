from django.core.management.base import BaseCommand, CommandError

from pages import translation_files


class Command(BaseCommand):
    help = (
        "Keeps the Spanish translation files (locale/es/LC_MESSAGES) in step with the site's text. "
        "'update' adds new English text to the .po files, 'compile' writes the .mo files Django reads, "
        "and 'check' reports anything untranslated or out of date."
    )

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["update", "compile", "check"])

    def handle(self, *args, action, **options):
        try:
            if action == "update":
                lines = translation_files.update()
            elif action == "compile":
                lines = translation_files.compile_all()
            else:
                problems = translation_files.status()
                if problems:
                    raise CommandError("Translations need attention:\n  " + "\n  ".join(problems))
                lines = ["Every piece of text has a translation, and the compiled files are up to date."]
        except translation_files.ExtractError as exc:
            raise CommandError(str(exc)) from exc
        for line in lines:
            self.stdout.write(line)
