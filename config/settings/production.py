from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

if not SECRET_KEY:  # noqa: F405
    raise ImproperlyConfigured("SECRET_KEY must be set in the environment for production.")

DEBUG = False

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

CSRF_TRUSTED_ORIGINS = [SITE_URL] if SITE_URL else []  # noqa: F405

# Deliberately NOT set yet (verify on Truehost first):
# - SECURE_HSTS_*: enable only after HTTPS is confirmed working end to end.
# - SECURE_PROXY_SSL_HEADER: depends on how Passenger/the proxy forwards HTTPS.

# ---- HTTPS hardening switches: turn on in .env only after HTTPS is verified on the host ----
SECURE_HSTS_SECONDS = int(os.environ.get("HSTS_SECONDS", "0"))  # start small (e.g. 3600), raise later
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("HSTS_INCLUDE_SUBDOMAINS", "").lower() in ("1", "true", "yes")
SECURE_HSTS_PRELOAD = False  # deliberately off: preload is very hard to undo
# Only enable if the host's proxy sets X-Forwarded-Proto itself (otherwise it can be spoofed).
if os.environ.get("BEHIND_HTTPS_PROXY", "").lower() in ("1", "true", "yes"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---- Static files (WhiteNoise) and storage locations for shared hosting ----
STATIC_ROOT = os.environ.get("STATIC_ROOT") or STATIC_ROOT
MEDIA_ROOT = os.environ.get("MEDIA_ROOT") or MEDIA_ROOT
MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
WHITENOISE_MANIFEST_STRICT = False  # a missing manifest entry must not turn a page into a 500