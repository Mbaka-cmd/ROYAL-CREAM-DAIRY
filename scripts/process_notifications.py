"""
cPanel cron entry point for the WhatsApp notification outbox.
Runs one batch: recovers stuck sends, applies webhook events, sends due notifications.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

import django

django.setup()

from django.core.management import call_command

call_command("process_notifications")