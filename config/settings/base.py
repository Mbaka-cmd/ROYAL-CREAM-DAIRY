import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


def env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


SECRET_KEY = os.environ.get("SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
SITE_URL = os.environ.get("SITE_URL", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.catalogue",
    "apps.customers",
    "apps.inventory",
    "apps.orders",
    "apps.delivery",
    "apps.notifications",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


def _database():
    engine = os.environ.get("DB_ENGINE", "sqlite").strip().lower()
    if engine in ("postgresql", "postgres"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", ""),
            "USER": os.environ.get("DB_USER", ""),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", ""),
            "PORT": os.environ.get("DB_PORT", ""),
            "OPTIONS": {"connect_timeout": 10},
        }
    return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}


DATABASES = {"default": _database()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "app.log"),
            "maxBytes": 1_000_000,
            "backupCount": 5,
            "formatter": "simple",
        },
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
}

from decimal import Decimal  # noqa: E402

DELIVERY_FEE = Decimal(os.environ.get("DELIVERY_FEE", "0.00"))


CHECKOUT_RATE_LIMIT = os.environ.get("CHECKOUT_RATE_LIMIT", "5/10m")
CART_VALIDATE_RATE_LIMIT = os.environ.get("CART_VALIDATE_RATE_LIMIT", "60/m")
DATA_UPLOAD_MAX_MEMORY_SIZE = 100_000

# ---- WhatsApp Cloud API (all secrets come from the environment) ----
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_BUSINESS_ACCOUNT_ID = os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")
# Deliberately no default: set this to a current Graph API version from Meta's docs (e.g. "vNN.0").
WHATSAPP_API_VERSION = os.environ.get("WHATSAPP_API_VERSION", "")
OWNER_WHATSAPP_NUMBER = os.environ.get("OWNER_WHATSAPP_NUMBER", "")
WHATSAPP_TEMPLATE_LANGUAGE = os.environ.get("WHATSAPP_TEMPLATE_LANGUAGE", "en")
WHATSAPP_TIMEOUT = (3.05, 8)  # (connect, read) seconds; never wait on Meta for long
NOTIFICATION_MAX_ATTEMPTS = int(os.environ.get("NOTIFICATION_MAX_ATTEMPTS", "5"))

_TEMPLATE_DEFAULTS = {
    "OWNER_NEW_ORDER": "rc_owner_new_order",
    "ORDER_RECEIVED": "rc_order_received",
    "ORDER_CONFIRMED": "rc_order_confirmed",
    "ORDER_OUT_FOR_DELIVERY": "rc_order_out_for_delivery",
    "ORDER_COMPLETED": "rc_order_completed",
    "ORDER_CANCELLED": "rc_order_cancelled",
    "DELIVERY_FAILED": "rc_delivery_failed",
}
WHATSAPP_TEMPLATE_NAMES = {
    event: os.environ.get(f"WHATSAPP_TEMPLATE_{event}", default)
    for event, default in _TEMPLATE_DEFAULTS.items()
}

# ---- Owner dashboard authentication ----
LOGIN_URL = "owner_login"
LOGIN_REDIRECT_URL = "owner_home"
LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "5/15m")            # per IP
LOGIN_USER_RATE_LIMIT = os.environ.get("LOGIN_USER_RATE_LIMIT", "10/15m")  # per username
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_HOURS", "12")) * 3600

# ---- Site identity, SEO, analytics, privacy ----
SITE_NAME = "Royal Cream Dairy"
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "").strip()
PUBLIC_WHATSAPP_NUMBER = os.environ.get("PUBLIC_WHATSAPP_NUMBER", "").strip()
SOCIAL_FACEBOOK_URL = os.environ.get("SOCIAL_FACEBOOK_URL", "").strip()
SOCIAL_TIKTOK_URL = os.environ.get("SOCIAL_TIKTOK_URL", "").strip()
GOOGLE_SITE_VERIFICATION = os.environ.get("GOOGLE_SITE_VERIFICATION", "").strip()
DEFAULT_OG_IMAGE = os.environ.get("DEFAULT_OG_IMAGE", "images/og-default.jpg").strip()  # social preview image under static/
PRIVACY_CONTACT_EMAIL = os.environ.get("PRIVACY_CONTACT_EMAIL", "").strip()
PERSONAL_DATA_RETENTION_MONTHS = int(os.environ.get("PERSONAL_DATA_RETENTION_MONTHS", "24"))

# ---- Media serving and backups ----
SERVE_MEDIA = os.environ.get("SERVE_MEDIA", "true").strip().lower() in ("1", "true", "yes")
BACKUP_DIR = os.environ.get("BACKUP_DIR") or str(Path.home() / "backups" / "royalcream")
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "14"))