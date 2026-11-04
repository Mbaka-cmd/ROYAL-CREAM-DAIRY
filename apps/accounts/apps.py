from django.apps import AppConfig
from django.db import DEFAULT_DB_ALIAS


def _ensure_roles_after_migrate(sender, **kwargs):
    # Runs once per migrate (the notifications app is the last one with models).
    if getattr(sender, "label", None) != "notifications":
        return
    from django.db.utils import OperationalError, ProgrammingError

    from .roles import ensure_roles

    try:
        ensure_roles(using=kwargs.get("using", DEFAULT_DB_ALIAS))
    except (OperationalError, ProgrammingError):
        pass


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self):
        from django.db.models.signals import post_migrate

        from . import signals  # noqa: F401

        post_migrate.connect(_ensure_roles_after_migrate, dispatch_uid="rc_ensure_roles")