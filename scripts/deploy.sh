#!/usr/bin/env bash
# Run on the server, inside the app's virtualenv, from anywhere:  bash scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.production}"

if [ -f requirements.lock.txt ]; then REQ=requirements.lock.txt; else REQ=requirements.txt; fi
echo "==> Installing dependencies from $REQ"
python -m pip install --upgrade pip
python -m pip install -r "$REQ"

echo "==> Backing up before changing anything"
python manage.py backup_data || echo "WARNING: pre-deploy backup failed (expected on the very first deploy)"

echo "==> Migrating database"
python manage.py migrate --noinput

echo "==> Collecting static files"
python manage.py collectstatic --noinput

echo "==> Refreshing dashboard roles"
python manage.py setup_roles

echo "==> Checks"
python manage.py check --deploy || true
python manage.py preflight || true

mkdir -p tmp
touch tmp/restart.txt
echo "==> Done. Passenger restarts on the next request (or press Restart in Setup Python App)."