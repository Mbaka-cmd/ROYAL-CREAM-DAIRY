from .base import *  # noqa: F401,F403

DEBUG = True
SECRET_KEY = SECRET_KEY or "dev-only-insecure-key-do-not-use-in-production"  # noqa: F405
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

# LocMemCache is fine for local development; production needs a shared cache (see deployment batch).
SILENCED_SYSTEM_CHECKS = ["django_ratelimit.W001", "django_ratelimit.E003"]