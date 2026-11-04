from django.core.management.base import BaseCommand

from apps.accounts.roles import ROLE_NAMES, ensure_roles


class Command(BaseCommand):
    help = "Create or refresh the dashboard role groups and their permissions."

    def handle(self, *args, **options):
        ensure_roles()
        self.stdout.write("Roles ready: " + ", ".join(ROLE_NAMES))