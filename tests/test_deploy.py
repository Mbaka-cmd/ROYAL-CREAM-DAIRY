import importlib
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts import roles
from apps.orders import services as order_services
from config import backup, preflight
from tests.helpers import make_variant

DB = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "royalcream",
    "USER": "royal",
    "PASSWORD": "s3cret-pw",
    "HOST": "localhost",
    "PORT": "5432",
}


class HealthTests(TestCase):
    def test_ok(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("no-store", response["Cache-Control"])

    def test_database_failure_is_503_without_details(self):
        with mock.patch("config.health.connection") as conn:
            conn.cursor.side_effect = Exception("password=hunter2 host=db.internal")
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "error"})
        self.assertNotIn("hunter2", response.content.decode())

    def test_only_safe_methods(self):
        self.assertEqual(self.client.head("/healthz/").status_code, 200)
        self.assertEqual(self.client.post("/healthz/").status_code, 405)

    def test_not_listed_for_crawlers(self):
        self.assertIn("Disallow: /healthz/", self.client.get("/robots.txt").content.decode())


class MediaServingTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (Path(self.tmp) / "products").mkdir()
        (Path(self.tmp) / "products" / "x.png").write_bytes(b"\x89PNG-test-bytes")
        secret = Path(self.tmp).parent / "rc_secret_test.txt"
        secret.write_text("top secret")
        self.addCleanup(lambda: secret.unlink(missing_ok=True))

    def test_serves_uploaded_files_with_caching(self):
        with override_settings(MEDIA_ROOT=self.tmp):
            response = self.client.get("/media/products/x.png")
            body = b"".join(response.streaming_content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, b"\x89PNG-test-bytes")
        self.assertIn("max-age=86400", response["Cache-Control"])
        self.assertIn("public", response["Cache-Control"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_path_traversal_is_refused(self):
        with override_settings(MEDIA_ROOT=self.tmp):
            for path in [
                "/media/../rc_secret_test.txt",
                "/media/%2e%2e/rc_secret_test.txt",
                "/media/products/../../rc_secret_test.txt",
            ]:
                with self.subTest(path=path):
                    response = self.client.get(path); self.assertIn(response.status_code, (400, 404)); self.assertNotIn(b"top secret", response.content)

    def test_no_directory_listing_and_missing_files(self):
        with override_settings(MEDIA_ROOT=self.tmp):
            self.assertEqual(self.client.get("/media/products/").status_code, 404)
            self.assertEqual(self.client.get("/media/").status_code, 404)
            self.assertEqual(self.client.get("/media/nope.png").status_code, 404)


class ProductionDeploySettingsTests(TestCase):
    KEYS = ["STATIC_ROOT", "MEDIA_ROOT", "HSTS_SECONDS", "HSTS_INCLUDE_SUBDOMAINS", "BEHIND_HTTPS_PROXY"]

    def load(self, **env):
        from config.settings import base

        if not base.SECRET_KEY:
            self.skipTest("SECRET_KEY is not set in this environment")
        clean = {k: v for k, v in os.environ.items() if k not in self.KEYS}
        clean.update(env)
        with mock.patch.dict(os.environ, clean, clear=True):
            module = importlib.import_module("config.settings.production")
            return importlib.reload(module)

    def test_whitenoise_sits_right_after_security_middleware(self):
        from config.settings import base

        prod = self.load()
        middleware = prod.MIDDLEWARE
        index = middleware.index("django.middleware.security.SecurityMiddleware")
        self.assertEqual(middleware[index + 1], "whitenoise.middleware.WhiteNoiseMiddleware")
        self.assertIn("config.middleware.SecurityHeadersMiddleware", middleware)
        self.assertNotIn("whitenoise.middleware.WhiteNoiseMiddleware", base.MIDDLEWARE)

    def test_static_storage_is_safe(self):
        prod = self.load()
        self.assertEqual(
            prod.STORAGES["staticfiles"]["BACKEND"], "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
        self.assertEqual(prod.STORAGES["default"]["BACKEND"], "django.core.files.storage.FileSystemStorage")
        self.assertIs(prod.WHITENOISE_MANIFEST_STRICT, False)

    def test_storage_locations_can_be_overridden(self):
        default = self.load()
        self.assertNotEqual(str(default.STATIC_ROOT), "/srv/static")
        prod = self.load(STATIC_ROOT="/srv/static", MEDIA_ROOT="/srv/media")
        self.assertEqual(str(prod.STATIC_ROOT), "/srv/static")
        self.assertEqual(str(prod.MEDIA_ROOT), "/srv/media")
        self.load()  # restore defaults


class BackupFunctionTests(TestCase):
    def fake_run(self, calls, fail=None):
        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if "--file" in cmd:
                Path(cmd[cmd.index("--file") + 1]).write_bytes(b"PGDMP-fake")
            if fail:
                raise fail
            return mock.Mock(returncode=0)

        return run

    def test_pg_dump_command_never_contains_the_password(self):
        cmd = backup.build_pg_dump_cmd("/usr/bin/pg_dump", DB, "/tmp/x.dump")
        text = " ".join(cmd)
        self.assertNotIn("s3cret-pw", text)
        for part in ["--format=custom", "--host", "localhost", "--port", "5432", "--username", "royal", "--dbname", "royalcream"]:
            self.assertIn(part, cmd)

    def test_sqlite_is_refused(self):
        with self.assertRaises(backup.BackupError):
            backup.create_backup(db={"ENGINE": "django.db.backends.sqlite3", "NAME": "x"})

    def test_missing_pg_dump_is_reported(self):
        with mock.patch("config.backup.shutil.which", return_value=None):
            with self.assertRaises(backup.BackupError) as ctx:
                backup.create_backup(db=DB, directory=tempfile.gettempdir())
        self.assertIn("pg_dump", str(ctx.exception))

    def test_create_backup_makes_dump_and_media_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp, "media")
            (media / "products").mkdir(parents=True)
            (media / "products" / "x.png").write_bytes(b"png")
            calls = []
            with mock.patch("config.backup.shutil.which", return_value="/usr/bin/pg_dump"), mock.patch(
                "config.backup.subprocess.run", side_effect=self.fake_run(calls)
            ):
                result = backup.create_backup(
                    db=DB, directory=Path(tmp, "backups"), media_root=media, keep=5,
                    now=datetime(2026, 11, 3, 10, 0, 0, tzinfo=dt_timezone.utc),
                )
            self.assertEqual(result.database.name, "db-20261103-100000.dump")
            self.assertTrue(result.database.exists())
            cmd, kwargs = calls[0]
            self.assertEqual(kwargs["env"]["PGPASSWORD"], "s3cret-pw")
            self.assertNotIn("s3cret-pw", " ".join(cmd))
            with tarfile.open(result.media) as tar:
                self.assertIn("media/products/x.png", tar.getnames())
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(result.database.stat().st_mode), 0o600)

    def test_failed_dump_leaves_no_partial_file_and_hides_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            error = subprocess.CalledProcessError(1, "pg_dump", stderr="boom " + "x" * 1000)
            with mock.patch("config.backup.shutil.which", return_value="/usr/bin/pg_dump"), mock.patch(
                "config.backup.subprocess.run", side_effect=self.fake_run([], fail=error)
            ):
                with self.assertRaises(backup.BackupError) as ctx:
                    backup.create_backup(db=DB, directory=Path(tmp, "b"), media_root=Path(tmp, "nomedia"))
            self.assertLessEqual(len(str(ctx.exception)), 500)
            self.assertEqual(list(Path(tmp, "b").glob("db-*")), [])

    def test_timeouts_and_missing_binaries_become_backup_errors(self):
        for exc in (subprocess.TimeoutExpired("pg_dump", 5), FileNotFoundError("nope")):
            with self.subTest(exc=type(exc).__name__), tempfile.TemporaryDirectory() as tmp:
                with mock.patch("config.backup.shutil.which", return_value="/usr/bin/pg_dump"), mock.patch(
                    "config.backup.subprocess.run", side_effect=exc
                ):
                    with self.assertRaises(backup.BackupError):
                        backup.create_backup(db=DB, directory=tmp, media_root=Path(tmp, "nomedia"))

    def test_prune_keeps_newest_per_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            for day in range(1, 6):
                Path(tmp, f"db-2026110{day}-000000.dump").write_text("x")
                Path(tmp, f"media-2026110{day}-000000.tar.gz").write_text("x")
            Path(tmp, "notes.txt").write_text("keep me")
            removed = backup.prune(tmp, 2)
            self.assertEqual(len(removed), 6)
            self.assertEqual(
                sorted(p.name for p in Path(tmp).glob("db-*")),
                ["db-20261104-000000.dump", "db-20261105-000000.dump"],
            )
            self.assertTrue(Path(tmp, "notes.txt").exists())

    def test_prune_never_removes_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "db-20261101-000000.dump").write_text("x")
            self.assertEqual(backup.prune(tmp, 0), [])
            self.assertEqual(len(list(Path(tmp).glob("db-*"))), 1)

    def test_latest_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(backup.latest_backup(tmp))
            Path(tmp, "db-20261101-000000.dump").write_text("x")
            Path(tmp, "db-20261103-000000.dump").write_text("x")
            self.assertEqual(backup.latest_backup(tmp).name, "db-20261103-000000.dump")
        self.assertIsNone(backup.latest_backup("/definitely/not/here"))

    def test_restore_refuses_the_live_database(self):
        with self.assertRaises(backup.BackupError) as ctx:
            backup.verify_restore("royalcream", db=DB, directory=tempfile.gettempdir())
        self.assertIn("live database", str(ctx.exception))

    def test_restore_needs_a_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(backup.BackupError):
                backup.verify_restore("scratch", db=DB, directory=tmp)

    def test_restore_runs_pg_restore_against_scratch(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "db-20261103-000000.dump").write_bytes(b"PGDMP")
            calls = []
            with mock.patch("config.backup.shutil.which", return_value="/usr/bin/pg_restore"), mock.patch(
                "config.backup.subprocess.run", side_effect=self.fake_run(calls)
            ):
                dump = backup.verify_restore("scratch_db", db=DB, directory=tmp)
            cmd, kwargs = calls[0]
            self.assertEqual(dump.name, "db-20261103-000000.dump")
            self.assertEqual(cmd[cmd.index("--dbname") + 1], "scratch_db")
            self.assertIn("--clean", cmd)
            self.assertNotIn("s3cret-pw", " ".join(cmd))
            self.assertEqual(kwargs["env"]["PGPASSWORD"], "s3cret-pw")


class BackupCommandTests(TestCase):
    def test_backup_command_reports_files(self):
        result = backup.BackupResult(Path("/b/db-1.dump"), Path("/b/media-1.tar.gz"), ["old"])
        out = StringIO()
        with mock.patch("config.backup.create_backup", return_value=result):
            call_command("backup_data", stdout=out)
        text = out.getvalue()
        self.assertIn("db-1.dump", text)
        self.assertIn("Removed 1 old backup", text)
        self.assertIn("Backup complete", text)

    def test_backup_command_fails_loudly_for_cron(self):
        with mock.patch("config.backup.create_backup", side_effect=backup.BackupError("disk full")):
            with self.assertRaises(CommandError) as ctx:
                call_command("backup_data")
        self.assertIn("disk full", str(ctx.exception))

    def test_check_backup_requires_confirmation(self):
        with self.assertRaises(CommandError):
            call_command("check_backup", "--scratch-db", "scratch")

    def test_check_backup_refuses_the_live_database(self):
        live = str(settings.DATABASES["default"]["NAME"])
        with self.assertRaises(CommandError):
            call_command("check_backup", "--scratch-db", live, "--yes")

    def test_check_backup_reports_counts(self):
        def counts(db, name, tables):
            return {t: (5 if name == "scratch" else 7) for t in tables}

        out = StringIO()
        with mock.patch("config.backup.verify_restore", return_value=Path("/b/db-1.dump")), mock.patch(
            "config.backup.table_counts", side_effect=counts
        ):
            call_command("check_backup", "--scratch-db", "scratch", "--yes", stdout=out)
        text = out.getvalue()
        self.assertIn("orders_order: backup=5 live=7", text)
        self.assertIn("Restore verified", text)

    def test_check_backup_fails_when_orders_table_missing(self):
        def counts(db, name, tables):
            return {t: (None if name == "scratch" else 1) for t in tables}

        with mock.patch("config.backup.verify_restore", return_value=Path("/b/db-1.dump")), mock.patch(
            "config.backup.table_counts", side_effect=counts
        ):
            with self.assertRaises(CommandError):
                call_command("check_backup", "--scratch-db", "scratch", "--yes")


class PreflightCheckTests(TestCase):
    def test_python_versions(self):
        self.assertEqual(preflight.check_python((3, 12, 1)).level, "PASS")
        self.assertEqual(preflight.check_python((3, 10, 9)).level, "WARN")
        self.assertEqual(preflight.check_python((3, 9, 18)).level, "FAIL")

    def test_settings_module(self):
        self.assertEqual(preflight.check_settings_module("config.settings.production").level, "PASS")
        self.assertEqual(preflight.check_settings_module("config.settings.development").level, "FAIL")
        self.assertEqual(preflight.check_settings_module("").level, "FAIL")

    def test_debug(self):
        with self.settings(DEBUG=True):
            self.assertEqual(preflight.check_debug().level, "FAIL")
        with self.settings(DEBUG=False):
            self.assertEqual(preflight.check_debug().level, "PASS")

    def test_secret_key(self):
        self.assertEqual(preflight.check_secret_key("x" * 60).level, "PASS")
        for bad in ["", "short", "dev-only-insecure-key-do-not-use-in-production" + "x" * 20]:
            with self.subTest(bad=bad[:12]):
                self.assertEqual(preflight.check_secret_key(bad).level, "FAIL")

    def test_secret_key_value_is_never_printed(self):
        self.assertNotIn("x" * 60, preflight.check_secret_key("x" * 60).detail)

    def test_allowed_hosts(self):
        self.assertEqual(preflight.check_allowed_hosts(["royalcreamdairy.co.ke"]).level, "PASS")
        self.assertEqual(preflight.check_allowed_hosts([".royalcreamdairy.co.ke"]).level, "PASS")
        self.assertEqual(preflight.check_allowed_hosts(["*"]).level, "FAIL")
        self.assertEqual(preflight.check_allowed_hosts([]).level, "FAIL")
        self.assertEqual(preflight.check_allowed_hosts(["localhost", "127.0.0.1"]).level, "WARN")

    def test_site_url(self):
        self.assertEqual(preflight.check_site_url("https://royalcreamdairy.co.ke").level, "PASS")
        self.assertEqual(preflight.check_site_url("http://royalcreamdairy.co.ke").level, "FAIL")
        self.assertEqual(preflight.check_site_url("").level, "FAIL")

    def test_secure_cookie_settings(self):
        secure = dict(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_SSL_REDIRECT=True)
        with self.settings(**secure):
            self.assertEqual(preflight.check_secure_cookies().level, "PASS")
        with self.settings(**{**secure, "SECURE_SSL_REDIRECT": False}):
            self.assertEqual(preflight.check_secure_cookies().level, "FAIL")

    def test_hsts(self):
        with self.settings(SECURE_HSTS_SECONDS=0):
            self.assertEqual(preflight.check_hsts().level, "WARN")
        with self.settings(SECURE_HSTS_SECONDS=3600):
            self.assertEqual(preflight.check_hsts().level, "PASS")

    def test_database_engine(self):
        self.assertEqual(preflight.check_database_engine("django.db.backends.postgresql").level, "PASS")
        self.assertEqual(preflight.check_database_engine("django.db.backends.sqlite3").level, "FAIL")
        self.assertEqual(preflight.check_database_engine("django.db.backends.mysql").level, "WARN")

    def test_database_connection_and_migrations(self):
        self.assertEqual(preflight.check_database_connection().level, "PASS")
        self.assertEqual(preflight.check_migrations().level, "PASS")

    def test_static_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(preflight.check_static_files(tmp).level, "FAIL")
            Path(tmp, "site.css").write_text("x")
            self.assertEqual(preflight.check_static_files(tmp).level, "PASS")
        self.assertEqual(preflight.check_static_files("/definitely/not/here").level, "FAIL")

    def test_media_and_log_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(preflight.check_media_writable(tmp).level, "PASS")
            self.assertEqual(preflight.check_log_writable(tmp).level, "PASS")
            blocker = Path(tmp, "a-file")
            blocker.write_text("x")
            self.assertEqual(preflight.check_media_writable(blocker / "sub").level, "FAIL")
            self.assertEqual(preflight.check_log_writable(blocker / "sub").level, "FAIL")

    def test_whatsapp_settings(self):
        full = dict(
            WHATSAPP_ACCESS_TOKEN="t", WHATSAPP_PHONE_NUMBER_ID="1", WHATSAPP_API_VERSION="v1.0",
            WHATSAPP_VERIFY_TOKEN="v", WHATSAPP_APP_SECRET="s", OWNER_WHATSAPP_NUMBER="+254700000001",
        )
        with self.settings(**full):
            self.assertEqual(preflight.check_whatsapp().level, "PASS")
        with self.settings(**{**full, "WHATSAPP_ACCESS_TOKEN": ""}):
            result = preflight.check_whatsapp()
        self.assertEqual(result.level, "WARN")
        self.assertIn("WHATSAPP_ACCESS_TOKEN", result.detail)
        self.assertNotIn("WHATSAPP_APP_SECRET", result.detail)

    def test_privacy_contact(self):
        with self.settings(PRIVACY_CONTACT_EMAIL=""):
            self.assertEqual(preflight.check_privacy_contact().level, "WARN")
        with self.settings(PRIVACY_CONTACT_EMAIL="privacy@shop.test"):
            self.assertEqual(preflight.check_privacy_contact().level, "PASS")

    def test_owner_account(self):
        self.assertEqual(preflight.check_owner_account().level, "FAIL")
        User.objects.create_superuser("owner", "o@example.com", "S3cure-Pass-Phrase!")
        self.assertEqual(preflight.check_owner_account().level, "PASS")

    def test_roles(self):
        roles.ensure_roles()
        self.assertEqual(preflight.check_roles().level, "PASS")
        Group.objects.filter(name__in=roles.ROLE_NAMES).delete()
        self.assertEqual(preflight.check_roles().level, "WARN")

    def test_catalogue_ready(self):
        self.assertEqual(preflight.check_catalogue_ready().level, "WARN")
        make_variant("80.00", 5)
        self.assertEqual(preflight.check_catalogue_ready().level, "PASS")

    @override_settings(DELIVERY_FEE=Decimal("0.00"))
    def test_notification_backlog(self):
        from apps.notifications.models import Notification

        self.assertEqual(preflight.check_notification_backlog().level, "PASS")
        milk = make_variant("80.00", 10)
        order_services.place_order(
            items=[{"variant_id": milk.id, "quantity": 1}], name="Jane Wanjiku", phone="0712345678",
            whatsapp_consent=True, delivery_area="Chuka", delivery_address="Main road",
            idempotency_key=uuid.uuid4().hex,
        )
        self.assertEqual(preflight.check_notification_backlog().level, "PASS")
        Notification.objects.update(created_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(preflight.check_notification_backlog().level, "WARN")

    def test_pg_dump_available(self):
        self.assertEqual(preflight.check_pg_dump(which=lambda name: "/usr/bin/" + name).level, "PASS")
        self.assertEqual(preflight.check_pg_dump(which=lambda name: None).level, "WARN")
        only_dump = lambda name: "/usr/bin/pg_dump" if name == "pg_dump" else None
        self.assertEqual(preflight.check_pg_dump(which=only_dump).level, "WARN")

    def test_backup_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(preflight.check_backups(tmp).level, "WARN")
            dump = Path(tmp, "db-20261103-000000.dump")
            dump.write_text("x")
            self.assertEqual(preflight.check_backups(tmp).level, "PASS")
            old = timezone.now().timestamp() - 3 * 86400
            os.utime(dump, (old, old))
            self.assertEqual(preflight.check_backups(tmp).level, "WARN")

    def test_run_checks_covers_everything(self):
        results = preflight.run_checks()
        self.assertGreaterEqual(len(results), 20)
        self.assertTrue(all(r.level in ("PASS", "WARN", "FAIL") for r in results))
        names = [r.name for r in results]
        self.assertEqual(len(names), len(set(names)))

    def test_a_crashing_check_becomes_a_fail_without_leaking_details(self):
        def check_broken_thing():
            raise RuntimeError("secret detail")

        with mock.patch.object(preflight, "CHECKS", [check_broken_thing]):
            results = preflight.run_checks()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].level, "FAIL")
        self.assertEqual(results[0].name, "Broken thing")
        self.assertIn("crashed", results[0].detail)
        self.assertNotIn("secret detail", results[0].detail)


class PreflightCommandTests(TestCase):
    def test_fails_on_a_development_setup_and_prints_every_result(self):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("preflight", stdout=out)
        text = out.getvalue()
        self.assertIn("[PASS]", text)
        self.assertIn("[FAIL]", text)
        self.assertIn("Summary:", text)

    def test_passes_when_nothing_fails(self):
        ok = [preflight.Result("PASS", "A", "fine"), preflight.Result("WARN", "B", "meh")]
        out = StringIO()
        with mock.patch("config.preflight.run_checks", return_value=ok):
            call_command("preflight", stdout=out)
        self.assertIn("Preflight passed", out.getvalue())
        self.assertIn("1 passed, 1 warnings, 0 failed", out.getvalue())