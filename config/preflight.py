import os
import shutil
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from . import backup

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "testserver"}


@dataclass
class Result:
    level: str
    name: str
    detail: str


def check_python(version_info=None):
    v = tuple(version_info or sys.version_info[:3])
    text = ".".join(str(p) for p in v[:3])
    if v < (3, 10):
        return Result(FAIL, "Python", f"{text}: Django 5.2 needs Python 3.10 or newer")
    if v < (3, 11):
        return Result(WARN, "Python", f"{text}: works with Django 5.2, but the project spec asks for 3.11+")
    return Result(PASS, "Python", text)


def check_settings_module(module=None):
    module = os.environ.get("DJANGO_SETTINGS_MODULE", "") if module is None else module
    if module.endswith("production"):
        return Result(PASS, "Settings module", module)
    return Result(FAIL, "Settings module", f"'{module}': set DJANGO_SETTINGS_MODULE=config.settings.production in .env")


def check_debug():
    if settings.DEBUG:
        return Result(FAIL, "DEBUG", "DEBUG is on")
    return Result(PASS, "DEBUG", "off")


def check_secret_key(key=None):
    key = settings.SECRET_KEY if key is None else key
    if not key:
        return Result(FAIL, "SECRET_KEY", "not set")
    if key.startswith("dev-only") or len(key) < 50:
        return Result(FAIL, "SECRET_KEY", f"weak or development key (length {len(key)})")
    return Result(PASS, "SECRET_KEY", f"set (length {len(key)})")


def check_allowed_hosts(hosts=None):
    hosts = list(settings.ALLOWED_HOSTS if hosts is None else hosts)
    if not hosts or "*" in hosts:
        return Result(FAIL, "ALLOWED_HOSTS", "empty or wildcard")
    if all(h in LOCAL_HOSTS for h in hosts):
        return Result(WARN, "ALLOWED_HOSTS", "only local hosts: add the real domain")
    return Result(PASS, "ALLOWED_HOSTS", ", ".join(hosts))


def check_site_url(url=None):
    url = settings.SITE_URL if url is None else url
    if (url or "").startswith("https://"):
        return Result(PASS, "SITE_URL", url)
    return Result(FAIL, "SITE_URL", f"'{url}': must be the https:// address of the live site")


def check_secure_cookies():
    ok = settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE and settings.SECURE_SSL_REDIRECT
    if ok:
        return Result(PASS, "HTTPS settings", "secure cookies and HTTPS redirect on")
    return Result(FAIL, "HTTPS settings", "secure cookies / SSL redirect are not all enabled")


def check_hsts():
    seconds = settings.SECURE_HSTS_SECONDS
    if seconds:
        return Result(PASS, "HSTS", f"{seconds} seconds")
    return Result(WARN, "HSTS", "off: set HSTS_SECONDS (start at 3600) once HTTPS works end to end")


def check_database_engine(engine=None):
    engine = settings.DATABASES["default"]["ENGINE"] if engine is None else engine
    if engine.endswith("postgresql"):
        return Result(PASS, "Database engine", "PostgreSQL")
    if engine.endswith("sqlite3"):
        return Result(FAIL, "Database engine", "SQLite cannot give the stock-locking guarantees checkout relies on")
    return Result(WARN, "Database engine", f"{engine}: untested; PostgreSQL is the supported database")


def check_database_connection():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return Result(PASS, "Database connection", "ok")


def check_migrations():
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if plan:
        return Result(FAIL, "Migrations", f"{len(plan)} pending: run manage.py migrate")
    return Result(PASS, "Migrations", "all applied")


def check_static_files(root=None):
    root = Path(root or settings.STATIC_ROOT)
    files = sum(1 for p in root.rglob("*") if p.is_file()) if root.is_dir() else 0
    if not files:
        return Result(FAIL, "Static files", f"{root} is empty: run manage.py collectstatic")
    return Result(PASS, "Static files", f"{files} files collected")


def _writable(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write_test"
    probe.write_text("ok")
    probe.unlink()


def check_media_writable(path=None):
    path = path or settings.MEDIA_ROOT
    try:
        _writable(path)
    except OSError as exc:
        return Result(FAIL, "Media folder", f"not writable ({type(exc).__name__}): product image uploads will fail")
    return Result(PASS, "Media folder", "writable")


def check_log_writable(path=None):
    path = path or settings.LOG_DIR
    try:
        _writable(path)
    except OSError as exc:
        return Result(FAIL, "Log folder", f"not writable ({type(exc).__name__})")
    return Result(PASS, "Log folder", "writable")


def check_whatsapp():
    names = [
        "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_API_VERSION",
        "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "OWNER_WHATSAPP_NUMBER",
    ]
    missing = [n for n in names if not getattr(settings, n, "")]
    if missing:
        return Result(WARN, "WhatsApp", "missing: " + ", ".join(missing) + " (orders still work; messages wait in the outbox)")
    return Result(PASS, "WhatsApp", "all settings present")


def check_privacy_contact():
    if settings.PRIVACY_CONTACT_EMAIL:
        return Result(PASS, "Privacy contact", "set")
    return Result(WARN, "Privacy contact", "PRIVACY_CONTACT_EMAIL is empty")


def check_owner_account():
    if get_user_model().objects.filter(is_superuser=True, is_active=True).exists():
        return Result(PASS, "Owner account", "exists")
    return Result(FAIL, "Owner account", "none: run manage.py createsuperuser")


def check_roles():
    from apps.accounts.roles import ROLE_NAMES

    if Group.objects.filter(name__in=ROLE_NAMES).count() == len(ROLE_NAMES):
        return Result(PASS, "Roles", "dashboard roles exist")
    return Result(WARN, "Roles", "missing: run manage.py setup_roles")


def check_catalogue_ready():
    from apps.catalogue.selectors import sellable_variants

    count = sellable_variants().filter(available__gt=0).count()
    if count:
        return Result(PASS, "Catalogue", f"{count} orderable item(s)")
    return Result(WARN, "Catalogue", "nothing orderable yet: add products and receive stock")


def check_notification_backlog():
    from apps.notifications.models import Notification

    cutoff = timezone.now() - timedelta(minutes=15)
    stuck = Notification.objects.filter(status=Notification.Status.PENDING, created_at__lt=cutoff).count()
    review = Notification.objects.filter(
        status__in=[Notification.Status.FAILED, Notification.Status.GAVE_UP]
    ).count()
    if stuck or review:
        return Result(WARN, "WhatsApp outbox", f"{stuck} unsent for 15+ min, {review} need review (is the cron job running?)")
    return Result(PASS, "WhatsApp outbox", "no backlog")


def check_pg_dump(which=shutil.which):
    if which("pg_dump") and which("pg_restore"):
        return Result(PASS, "pg_dump / pg_restore", "available")
    return Result(WARN, "pg_dump / pg_restore", "not found on PATH: automated backups will not work")


def check_backups(directory=None, now=None):
    latest = backup.latest_backup(directory or settings.BACKUP_DIR)
    if latest is None:
        return Result(WARN, "Backups", "no database backup found yet")
    now = now or timezone.now()
    age = (now.timestamp() - latest.stat().st_mtime) / 3600
    if age > 36:
        return Result(WARN, "Backups", f"newest backup is {age:.0f} hours old")
    return Result(PASS, "Backups", f"newest backup is {age:.1f} hours old")


CHECKS = [
    check_python, check_settings_module, check_debug, check_secret_key, check_allowed_hosts,
    check_site_url, check_secure_cookies, check_hsts, check_database_engine,
    check_database_connection, check_migrations, check_static_files, check_media_writable,
    check_log_writable, check_whatsapp, check_privacy_contact, check_owner_account,
    check_roles, check_catalogue_ready, check_notification_backlog, check_pg_dump, check_backups,
]


def run_checks():
    results = []
    for check in CHECKS:
        try:
            results.append(check())
        except Exception as exc:
            name = check.__name__.replace("check_", "").replace("_", " ").capitalize()
            results.append(Result(FAIL, name, f"check crashed: {type(exc).__name__}"))
    return results