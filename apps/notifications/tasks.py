import logging
import re
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from . import webhooks, whatsapp
from .models import Notification, WebhookEvent

logger = logging.getLogger(__name__)

BACKOFF_MINUTES = (1, 5, 15, 60, 180)
STALE_CLAIM = timedelta(minutes=5)
EVENT_EXPIRY = timedelta(days=1)
WEBHOOK_REPLAY_LIMIT = 200


def _digits(raw):
    return re.sub(r"\D", "", raw or "")


def _recipient(note):
    if note.recipient_type == Notification.Recipient.OWNER:
        return _digits(settings.OWNER_WHATSAPP_NUMBER)
    return _digits(note.recipient_phone)


def _update(pk, **fields):
    Notification.objects.filter(pk=pk).update(updated_at=timezone.now(), **fields)


def _record_failure(note, attempts, exc, now):
    error = str(exc)[:500]
    if exc.retriable:
        if attempts >= settings.NOTIFICATION_MAX_ATTEMPTS:
            _update(note.pk, status=Notification.Status.GAVE_UP, last_error=error, status_updated_at=now)
            outcome = "gave_up"
        else:
            delay = BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)]
            _update(
                note.pk,
                status=Notification.Status.PENDING,
                last_error=error,
                next_attempt_at=now + timedelta(minutes=delay),
            )
            outcome = "retry"
    else:
        _update(note.pk, status=Notification.Status.FAILED, last_error=error, status_updated_at=now)
        outcome = "failed"
    logger.warning("WhatsApp notification %s: %s (attempt %s)", note.pk, outcome, attempts)
    return outcome


def attempt_send(notification_id, *, now=None):
    """One send attempt. Safe to call from several processes: only one can claim a row."""
    now = now or timezone.now()
    note = Notification.objects.select_related("order__customer").filter(pk=notification_id).first()
    if note is None:
        return "missing"
    if note.status != Notification.Status.PENDING or note.next_attempt_at > now:
        return "not_due"

    to = _recipient(note)
    if not whatsapp.is_configured() or not to:
        return "not_configured"

    if (
        note.recipient_type == Notification.Recipient.CUSTOMER
        and not note.order.customer.whatsapp_opt_in
    ):
        Notification.objects.filter(pk=note.pk, status=Notification.Status.PENDING).update(
            status=Notification.Status.SKIPPED,
            last_error="Customer has no WhatsApp consent",
            status_updated_at=now,
            updated_at=now,
        )
        return "skipped"

    claimed = Notification.objects.filter(pk=note.pk, status=Notification.Status.PENDING).update(
        status=Notification.Status.SENDING,
        claimed_at=now,
        attempts=F("attempts") + 1,
        updated_at=now,
    )
    if claimed != 1:
        return "not_claimed"
    attempts = Notification.objects.values_list("attempts", flat=True).get(pk=note.pk)

    try:
        message_id = whatsapp.send_template(
            to_phone=to, template_name=note.template_name, params=note.params
        )
    except whatsapp.WhatsAppError as exc:
        return _record_failure(note, attempts, exc, now)
    except Exception as exc:  # unexpected: treat as retriable, never crash the caller
        logger.exception("Unexpected error sending notification %s", note.pk)
        return _record_failure(
            note, attempts, whatsapp.WhatsAppError(f"Unexpected error: {type(exc).__name__}", retriable=True), now
        )

    _update(
        note.pk,
        status=Notification.Status.SENT,
        message_id=message_id,
        sent_at=now,
        last_error="",
        status_updated_at=now,
    )
    return "sent"


def dispatch_now(notification_ids):
    """Immediate attempt right after the order transaction commits. Never raises."""
    for notification_id in notification_ids:
        try:
            attempt_send(notification_id)
        except Exception:
            logger.exception("WhatsApp dispatch failed for notification %s", notification_id)


def process_outbox(*, batch_size=20, now=None):
    """Cron entry point: recover stuck rows, replay webhook events, send due notifications."""
    now = now or timezone.now()
    counts = Counter()

    recovered = Notification.objects.filter(
        status=Notification.Status.SENDING, claimed_at__lt=now - STALE_CLAIM
    ).update(status=Notification.Status.PENDING, next_attempt_at=now, updated_at=now)
    if recovered:
        counts["recovered"] = recovered

    WebhookEvent.objects.filter(processed=False, created_at__lt=now - EVENT_EXPIRY).update(processed=True)
    pending_events = WebhookEvent.objects.filter(processed=False).order_by("event_timestamp", "id")
    for event in pending_events[:WEBHOOK_REPLAY_LIMIT]:
        if webhooks.apply_event(event):
            counts["events_applied"] += 1

    due_ids = list(
        Notification.objects.filter(status=Notification.Status.PENDING, next_attempt_at__lte=now)
        .order_by("id")
        .values_list("id", flat=True)[:batch_size]
    )
    for notification_id in due_ids:
        try:
            outcome = attempt_send(notification_id, now=now)
        except Exception:
            logger.exception("Outbox error for notification %s", notification_id)
            outcome = "error"
        counts[outcome] += 1
    return counts