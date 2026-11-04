from django.core.management.base import BaseCommand

from apps.notifications import tasks


class Command(BaseCommand):
    help = "Process the WhatsApp notification outbox (run from cron)."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=20, help="Max notifications per run")

    def handle(self, *args, **options):
        counts = tasks.process_outbox(batch_size=options["batch"])
        if counts:
            summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
            self.stdout.write(f"Outbox: {summary}")
        else:
            self.stdout.write("Outbox: nothing to do")