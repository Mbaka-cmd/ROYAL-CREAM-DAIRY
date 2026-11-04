from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config import backup

TABLES = [
    "catalogue_product",
    "inventory_inventory",
    "customers_customer",
    "orders_order",
    "notifications_notification",
]


class Command(BaseCommand):
    help = "Restore the newest backup into a SCRATCH database and compare row counts (a backup is not verified until restored)."

    def add_arguments(self, parser):
        parser.add_argument("--scratch-db", required=True, help="An empty spare database (never the live one)")
        parser.add_argument("--yes", action="store_true", help="Confirm: the scratch database is overwritten")

    def handle(self, *args, **options):
        if not options["yes"]:
            raise CommandError("This overwrites the scratch database. Re-run with --yes to confirm.")
        db = settings.DATABASES["default"]
        scratch = options["scratch_db"]
        try:
            dump = backup.verify_restore(scratch, db=db)
            live = backup.table_counts(db, db["NAME"], TABLES)
            restored = backup.table_counts(db, scratch, TABLES)
        except backup.BackupError as exc:
            raise CommandError(str(exc))
        except Exception as exc:
            raise CommandError(f"Could not read table counts: {type(exc).__name__}")
        self.stdout.write(f"Restored {dump.name} into {scratch}")
        for table in TABLES:
            self.stdout.write(f"  {table}: backup={restored.get(table)} live={live.get(table)}")
        if restored.get("orders_order") is None:
            raise CommandError("Restore check FAILED: the orders table is missing in the restored copy.")
        self.stdout.write(self.style.SUCCESS("Restore verified."))