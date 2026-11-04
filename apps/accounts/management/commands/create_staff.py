import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.roles import ROLE_NAMES, ROLE_OWNER, ensure_roles


class Command(BaseCommand):
    help = "Create a dashboard user in one of the roles. The password is asked for interactively."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--role", required=True, choices=ROLE_NAMES)
        parser.add_argument("--email", default="")

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"].strip()
        if not username:
            raise CommandError("Username cannot be empty.")
        if User.objects.filter(username=username).exists():
            raise CommandError(f"User '{username}' already exists.")

        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Password (again): "):
            raise CommandError("Passwords do not match.")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages))

        ensure_roles()
        user = User.objects.create_user(
            username=username,
            email=options["email"],
            password=password,
            is_staff=options["role"] == ROLE_OWNER,
        )
        user.groups.add(Group.objects.get(name=options["role"]))
        self.stdout.write(f"Created {options['role']} user '{username}'.")