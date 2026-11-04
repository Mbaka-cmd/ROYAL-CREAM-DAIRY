from django.core.management.base import BaseCommand, CommandError

from apps.notifications import services
from apps.notifications.models import Notification


class Command(BaseCommand):
    help = "Re-queue FAILED / GAVE_UP notifications (after fixing the cause, e.g. an expired token)."

    def add_arguments(self, parser):
        parser.add_argument("--ids", type=int, nargs="+", help="Notification ids")
        parser.add_argument("--failed", action="store_true", help="All FAILED and GAVE_UP notifications")

    def handle(self, *args, **options):
        if options["failed"]:
            ids = list(
                Notification.objects.filter(
                    status__in=[Notification.Status.FAILED, Notification.Status.GAVE_UP]
                ).values_list("pk", flat=True)
            )
        elif options["ids"]:
            ids = options["ids"]
        else:
            raise CommandError("Give --ids ... or --failed")
        self.stdout.write(f"Re-queued {services.requeue(ids)} notification(s).")