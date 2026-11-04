import logging

from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(user_login_failed)
def log_failed_login(sender, credentials, request=None, **kwargs):
    ip = request.META.get("REMOTE_ADDR", "?") if request is not None else "?"
    username = str((credentials or {}).get("username", ""))[:50]
    logger.warning("Failed login for username=%r from %s", username, ip)