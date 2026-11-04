from django.core.management.base import BaseCommand, CommandError

from apps.inventory import services


class Command(BaseCommand):
    help = "Record stock received for a variant (opening stock or restock)."

    def add_arguments(self, parser):
        parser.add_argument("--variant", type=int, required=True, help="ProductVariant id")
        parser.add_argument("--qty", type=int, required=True)
        parser.add_argument("--reason", default="Stock received")

    def handle(self, *args, **options):
        try:
            row = services.receive_stock(options["variant"], options["qty"], reason=options["reason"])
        except services.InventoryError as exc:
            raise CommandError(str(exc))
        self.stdout.write(
            self.style.SUCCESS(f"{row.variant}: on hand {row.quantity_on_hand}, available {row.available}")
        )