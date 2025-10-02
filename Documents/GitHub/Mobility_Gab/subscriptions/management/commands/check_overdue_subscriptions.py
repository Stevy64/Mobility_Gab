from django.core.management.base import BaseCommand

from subscriptions.tasks import handle_overdue_subscriptions


class Command(BaseCommand):
    help = "Check subscriptions for overdue payments and suspend accounts when necessary."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les comptes concernés sans appliquer de suspension.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        if dry_run:
            self.stdout.write(self.style.WARNING("Mode simulation – aucun changement ne sera appliqué."))

        results = handle_overdue_subscriptions(dry_run=dry_run)

        overdue = results.get("overdue", 0)
        suspended = results.get("suspended", 0)

        message = f"Abonnements en retard: {overdue} | Comptes suspendus: {suspended}"
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Simulation terminée. {message}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Vérification terminée. {message}"))
