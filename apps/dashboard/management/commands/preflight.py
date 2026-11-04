from django.core.management.base import BaseCommand, CommandError

from config import preflight


class Command(BaseCommand):
    help = "Go-live checklist: verifies configuration, database, files and integrations on this server."

    def handle(self, *args, **options):
        results = preflight.run_checks()
        styles = {preflight.PASS: self.style.SUCCESS, preflight.WARN: self.style.WARNING, preflight.FAIL: self.style.ERROR}
        for result in results:
            self.stdout.write(styles[result.level](f"[{result.level}] {result.name}: {result.detail}"))
        counts = {level: sum(1 for r in results if r.level == level) for level in (preflight.PASS, preflight.WARN, preflight.FAIL)}
        self.stdout.write(f"\nSummary: {counts['PASS']} passed, {counts['WARN']} warnings, {counts['FAIL']} failed")
        if counts["FAIL"]:
            raise CommandError("Preflight failed: fix the [FAIL] items above before going live.")
        self.stdout.write(self.style.SUCCESS("Preflight passed."))