# Deploying Royal Cream Dairy on Truehost cPanel

Verify each "check" item against your actual Truehost plan; they are the things this guide cannot know.
Throughout, replace YOURUSER with your cPanel username and 3.12 with the Python version you choose.

## 0. Before you start
- Commit and push the code to a private GitHub repository. `.env` is ignored by git and must never be committed.
- Run `.\scripts\run_tests_postgres.ps1` locally (see docs/postgres_windows.md). Fix anything it finds first.
- Check: the plan offers "Setup Python App" (Python 3.11 or newer; 3.10 minimum), "PostgreSQL Databases",
  "Cron Jobs", Terminal or SSH access, and AutoSSL. If PostgreSQL is not available, stop and tell me:
  a MySQL/MariaDB variant needs extra code and testing.

## 1. Domain and HTTPS
- Register royalcreamdairy.co.ke (a .co.ke registrar such as Truehost) and point it at the hosting account.
- In cPanel run AutoSSL so the site works over https:// before you set SECURE settings or HSTS.

## 2. Databases (cPanel > PostgreSQL Databases)
- Create a database and a user, give the user all privileges on it. cPanel normally prefixes names with your
  account name (for example YOURUSER_royalcream).
- Create a second empty database for restore tests (for example YOURUSER_rc_scratch) with the same user.

## 3. Create the application (cPanel > Setup Python App)
- Python version: the newest of 3.12 / 3.11. Application root: royal_cream. Application URL: the domain.
- Startup file: passenger_wsgi.py   Entry point: application
- Get the code into ~/royal_cream: use cPanel "Git Version Control" to clone the repository there (the folder
  must be empty first), or git clone over SSH.
- If cPanel replaced passenger_wsgi.py with its own, restore ours: `cd ~/royal_cream && git checkout -- passenger_wsgi.py`
- Static files are served by the app itself (WhiteNoise). Product images are served by the app too
  (SERVE_MEDIA=True). If you prefer Apache to serve images, set MEDIA_ROOT to a folder under public_html,
  set SERVE_MEDIA=False and make sure that folder is web-visible.

## 4. Terminal: environment file
Open Terminal (or SSH). cPanel shows the exact activate command on the app page; it looks like:

    source /home/YOURUSER/virtualenv/royal_cream/3.12/bin/activate && cd /home/YOURUSER/royal_cream

Create the production environment file and lock it down:

    cp .env.example .env
    nano .env
    chmod 600 .env

Set at least: DJANGO_SETTINGS_MODULE=config.settings.production, DEBUG=False, a NEW random SECRET_KEY,
ALLOWED_HOSTS=royalcreamdairy.co.ke,www.royalcreamdairy.co.ke, SITE_URL=https://royalcreamdairy.co.ke,
DB_ENGINE=postgresql with the DB_* values from step 2, DELIVERY_FEE, PRIVACY_CONTACT_EMAIL, BACKUP_DIR
(a folder OUTSIDE public_html, e.g. /home/YOURUSER/backups/royalcream), and the WHATSAPP_* values
(see docs/whatsapp_templates.md). Generate a secret key with:

    python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"

## 5. First deploy
    bash scripts/deploy.sh
    python manage.py createsuperuser
    python manage.py create_staff --username amina --role "Order Manager"

The script installs requirements (requirements.lock.txt if present), backs up, migrates, collects static
files, refreshes roles, runs the checks and restarts the app. Read the preflight output: every [FAIL] must be
fixed; [WARN] items are your call. Check: if the lock file fails to install on the server's Python, delete it
and the script falls back to requirements.txt.

## 6. Cron jobs (cPanel > Cron Jobs)
Use the full path to the virtualenv's python (from the activate line above).

    * * * * * cd /home/YOURUSER/royal_cream && /home/YOURUSER/virtualenv/royal_cream/3.12/bin/python scripts/process_notifications.py > /dev/null 2>> logs/cron-errors.log
    30 2 * * * cd /home/YOURUSER/royal_cream && /home/YOURUSER/virtualenv/royal_cream/3.12/bin/python manage.py backup_data > /dev/null 2>> logs/cron-errors.log
    15 3 1 * * cd /home/YOURUSER/royal_cream && /home/YOURUSER/virtualenv/royal_cream/3.12/bin/python manage.py purge_personal_data > /dev/null 2>> logs/cron-errors.log

Check: the minimum interval Truehost allows. If it is not one minute, WhatsApp retries run at that interval.

## 7. Backups you can trust
- Run once by hand: `python manage.py backup_data`
- Prove a restore works: `python manage.py check_backup --scratch-db YOURUSER_rc_scratch --yes`
  (it refuses to run against the live database).
- Copy backups OFF the server regularly (download them, or sync to cloud storage). A backup that lives
  only on the same account is not enough.

## 8. WhatsApp
Follow docs/whatsapp_templates.md: approve the 7 templates, set the webhook to
https://royalcreamdairy.co.ke/webhooks/whatsapp/ with your verify token, subscribe to `messages`, then place a
real test order and watch Dashboard > Messages.

## 9. Smoke test (do all of these on a phone)
- Home page loads over https; products and prices are right.
- Add to cart, check out as a guest, see the confirmation page.
- Owner receives the WhatsApp message; customer receives theirs (with consent ticked).
- Dashboard login works; confirm, prepare, deliver the order; stock goes down.
- /healthz/ shows {"status": "ok"}. Add it to an uptime monitor (for example UptimeRobot).
- /robots.txt and /sitemap.xml look right. Submit the sitemap in Google Search Console.

## 10. Turn on HSTS (only after everything above works over https)
Set HSTS_SECONDS=3600 in .env, restart, test for a day, then raise it (for example 31536000). If the site is
behind a proxy that sets X-Forwarded-Proto itself, set BEHIND_HTTPS_PROXY=True; otherwise leave it off. If you
see a redirect loop after enabling SECURE settings, that is the first thing to check.

## 11. Updating later
    cd ~/royal_cream && git pull && bash scripts/deploy.sh
To roll back: `git checkout <previous-commit>`, run `bash scripts/deploy.sh`, and if a migration must be
undone restore the pre-deploy backup (pg_restore) rather than guessing.