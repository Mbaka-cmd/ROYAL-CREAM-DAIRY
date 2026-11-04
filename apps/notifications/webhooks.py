import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Notification, WebhookEvent

logger = logging.getLogger(__name__)

TRACKED_STATUSES = {"sent", "delivered", "read", "failed"}

# Delivery only moves forward; events can arrive out of order.
RANK = {
    Notification.Status.PENDING: 0,
    Notification.Status.SENDING: 0,
    Notification.Status.SKIPPED: 0,
    Notification.Status.FAILED: 0,
    Notification.Status.GAVE_UP: 0,
    Notification.Status.SENT: 1,
    Notification.Status.DELIVERED: 2,
    Notification.Status.READ: 3,
}
TARGET = {
    "sent": Notification.Status.SENT,
    "delivered": Notification.Status.DELIVERED,
    "read": Notification.Status.READ,
}


def valid_signature(raw_body, header, secret):
    algo, _, digest = (header or "").partition("=")
    if algo != "sha256" or not digest:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest.strip().lower().encode(), expected.encode())


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def apply_event(event):
    """Apply one stored status event. Returns False if the message is not known yet."""
    with transaction.atomic():
        note = Notification.objects.select_for_update().filter(message_id=event.message_id).first()
        if note is None:
            return False
        now = timezone.now()
        current = note.status
        changed = False
        if event.status == "failed":
            if current not in (Notification.Status.DELIVERED, Notification.Status.READ):
                note.status = Notification.Status.FAILED
                note.last_error = f"{event.error_code} {event.error_title}".strip()[:500]
                changed = True
        else:
            target = TARGET[event.status]
            if RANK[target] > RANK.get(current, 0):
                note.status = target
                changed = True
        if changed:
            note.status_updated_at = now
            note.save(update_fields=["status", "last_error", "status_updated_at", "updated_at"])
        event.processed = True
        event.save(update_fields=["processed"])
    return True


def ingest_payload(payload):
    """Store and apply every status event in a webhook payload. Idempotent."""
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            value = change.get("value") if isinstance(change, dict) else None
            if not isinstance(value, dict):
                continue
            for item in value.get("statuses") or []:
                if not isinstance(item, dict):
                    continue
                message_id = str(item.get("id") or "")[:128]
                status = str(item.get("status") or "").lower()
                if not message_id or status not in TRACKED_STATUSES:
                    continue
                errors = item.get("errors")
                first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
                event, created = WebhookEvent.objects.get_or_create(
                    message_id=message_id,
                    status=status,
                    event_timestamp=_to_int(item.get("timestamp")),
                    defaults={
                        "error_code": str(first.get("code", ""))[:20],
                        "error_title": str(first.get("title") or first.get("message") or "")[:200],
                    },
                )
                if created:
                    apply_event(event)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    if request.method == "GET":
        return _verify(request)
    return _receive(request)


def _verify(request):
    expected = settings.WHATSAPP_VERIFY_TOKEN
    mode = request.GET.get("hub.mode")
    token = request.GET.get("hub.verify_token", "")
    challenge = request.GET.get("hub.challenge", "")
    if expected and mode == "subscribe" and hmac.compare_digest(token.encode(), expected.encode()):
        return HttpResponse(challenge, content_type="text/plain")
    logger.warning("WhatsApp webhook verification failed")
    return HttpResponse(status=403)


def _receive(request):
    secret = settings.WHATSAPP_APP_SECRET
    if not secret:
        logger.error("WhatsApp webhook received but WHATSAPP_APP_SECRET is not set")
        return HttpResponse(status=503)
    try:
        raw = request.body
    except RequestDataTooBig:
        return HttpResponse(status=413)
    if not valid_signature(raw, request.headers.get("X-Hub-Signature-256", ""), secret):
        logger.warning("WhatsApp webhook rejected: invalid signature")
        return HttpResponse(status=403)
    try:
        payload = json.loads(raw)
    except ValueError:
        return HttpResponse(status=400)
    if not isinstance(payload, dict):
        return HttpResponse(status=400)
    ingest_payload(payload)
    return HttpResponse(status=200)