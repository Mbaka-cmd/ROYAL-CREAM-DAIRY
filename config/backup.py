import logging
import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class BackupError(Exception):
    pass


@dataclass
class BackupResult:
    database: Path
    media: Path = None
    removed: list = field(default_factory=list)


def _is_postgres(db):
    return str(db.get("ENGINE", "")).endswith("postgresql")


def connection_args(db):
    args = []
    if db.get("HOST"):
        args += ["--host", str(db["HOST"])]
    if db.get("PORT"):
        args += ["--port", str(db["PORT"])]
    if db.get("USER"):
        args += ["--username", str(db["USER"])]
    return args


def build_pg_dump_cmd(pg_dump, db, target):
    return [
        pg_dump, "--format=custom", "--no-owner", "--no-privileges",
        "--file", str(target), *connection_args(db), "--dbname", str(db["NAME"]),
    ]


def build_pg_restore_cmd(pg_restore, db, source, scratch_name):
    return [
        pg_restore, "--no-owner", "--no-privileges", "--clean", "--if-exists",
        *connection_args(db), "--dbname", scratch_name, str(source),
    ]


def _env(db):
    env = dict(os.environ)
    if db.get("PASSWORD"):
        env["PGPASSWORD"] = str(db["PASSWORD"])  # never on the command line
    return env


def _run(cmd, db, timeout=900):
    try:
        subprocess.run(cmd, check=True, env=_env(db), capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        raise BackupError((exc.stderr or "command failed").strip()[-500:]) from None
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackupError(f"{type(exc).__name__}: could not run {Path(str(cmd[0])).name}") from None


def _restrict(path, mode):
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def prune(directory, keep):
    """Keep only the newest `keep` database dumps and media archives. Returns removed file names."""
    keep = max(1, int(keep))
    removed = []
    directory = Path(directory)
    for prefix in ("db-", "media-"):
        files = sorted(p for p in directory.iterdir() if p.is_file() and p.name.startswith(prefix))
        for old in files[:-keep]:
            old.unlink()
            removed.append(old.name)
    return removed


def latest_backup(directory):
    directory = Path(directory).expanduser()
    if not directory.is_dir():
        return None
    dumps = sorted(p for p in directory.iterdir() if p.is_file() and p.name.startswith("db-") and p.suffix == ".dump")
    return dumps[-1] if dumps else None


def create_backup(db=None, now=None, directory=None, keep=None, media_root=None):
    db = db or settings.DATABASES["default"]
    if not _is_postgres(db):
        raise BackupError("Backups use pg_dump and need a PostgreSQL database.")
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise BackupError("pg_dump was not found on this server.")

    directory = Path(directory or settings.BACKUP_DIR).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    _restrict(directory, 0o700)

    stamp = (now or timezone.now()).strftime("%Y%m%d-%H%M%S")
    target = directory / f"db-{stamp}.dump"
    try:
        _run(build_pg_dump_cmd(pg_dump, db, target), db)
    except BackupError:
        target.unlink(missing_ok=True)
        raise
    _restrict(target, 0o600)

    media_path = None
    media_dir = Path(media_root or settings.MEDIA_ROOT)
    if media_dir.is_dir():
        media_path = directory / f"media-{stamp}.tar.gz"
        with tarfile.open(media_path, "w:gz") as tar:
            tar.add(media_dir, arcname="media")
        _restrict(media_path, 0o600)

    removed = prune(directory, keep if keep is not None else settings.BACKUP_KEEP)
    logger.info("Backup created: %s", target.name)
    return BackupResult(target, media_path, removed)


def verify_restore(scratch_name, db=None, directory=None):
    """Restore the newest dump into a SCRATCH database. Refuses to touch the live database."""
    db = db or settings.DATABASES["default"]
    if str(scratch_name) == str(db.get("NAME")):
        raise BackupError("Refusing: the scratch database must not be the live database.")
    if not _is_postgres(db):
        raise BackupError("Restore checks need a PostgreSQL database.")
    dump = latest_backup(directory or settings.BACKUP_DIR)
    if dump is None:
        raise BackupError("No database backup found to restore.")
    pg_restore = shutil.which("pg_restore")
    if not pg_restore:
        raise BackupError("pg_restore was not found on this server.")
    _run(build_pg_restore_cmd(pg_restore, db, dump, scratch_name), db)
    return dump


def table_counts(db, name, tables):
    import psycopg
    from psycopg import sql

    kwargs = {"dbname": name}
    for key, arg in (("HOST", "host"), ("PORT", "port"), ("USER", "user"), ("PASSWORD", "password")):
        if db.get(key):
            kwargs[arg] = db[key]
    counts = {}
    with psycopg.connect(connect_timeout=10, **kwargs) as conn:
        for table in tables:
            try:
                counts[table] = conn.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
            except psycopg.Error:
                conn.rollback()
                counts[table] = None
    return counts