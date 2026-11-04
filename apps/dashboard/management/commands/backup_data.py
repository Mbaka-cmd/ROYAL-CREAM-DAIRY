from django.core.management.base import BaseCommand, CommandError

from config import backup


class Command(BaseCommand):
    help = "Back up the database (pg_dump) and uploaded media; keeps the newest BACKUP_KEEP of each."

    def handle(self, *args, **options):
        try:
            result = backup.create_backup()
        except backup.BackupError as exc:
            raise CommandError(f"Backup failed: {exc}")
        self.stdout.write(f"Database: {result.database}")
        if result.media:
            self.stdout.write(f"Media:    {result.media}")
        if result.removed:
            self.stdout.write(f"Removed {len(result.removed)} old backup file(s).")
        self.stdout.write(self.style.SUCCESS("Backup complete."))