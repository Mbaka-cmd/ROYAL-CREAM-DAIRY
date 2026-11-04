from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.customers import privacy


class Command(BaseCommand):
    help = "Anonymise customers whose last order is older than the retention period (run monthly from cron)."

    def add_arguments(self, parser):
        parser.add_argument("--months", type=int, default=settings.PERSONAL_DATA_RETENTION_MONTHS)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        months = options["months"]
        if months < 1:
            raise CommandError("--months must be at least 1.")
        done = skipped = 0
        for customer in privacy.customers_due_for_purge(months):
            if options["dry_run"]:
                done += 1
                continue
            try:
                done += 1 if privacy.anonymize_customer(customer) else 0
            except privacy.OpenOrdersError:
                skipped += 1
        verb = "Would anonymise" if options["dry_run"] else "Anonymised"
        self.stdout.write(f"{verb} {done} customer(s); skipped {skipped} with open orders.")