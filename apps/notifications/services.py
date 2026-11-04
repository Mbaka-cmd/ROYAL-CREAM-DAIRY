import re
from functools import partial

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import tasks
from .models import Notification

EVENT_FOR_STATUS = {
    "CONFIRMED": Notification.Event.ORDER_CONFIRMED,
    "OUT_FOR_DELIVERY": Notification.Event.ORDER_OUT_FOR_DELIVERY,
    "COMPLETED": Notification.Event.ORDER_COMPLETED,
    "CANCELLED": Notification.Event.ORDER_CANCELLED,
    # status -> customer notification event (statuses not listed send nothing)
    "DELIVERY_FAILED": Notification.Event.DELIVERY_FAILED,
}


def _clean(text, limit=100):
    """Template parameters must be single-line and bounded (no newlines/tabs/long space runs)."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text or "-"


def _money(value):
    text = f"{value:.2f}"
    return text[:-3] if text.endswith(".00") else text


def _items_summary(order):
    parts = [f"{i.quantity} x {i.product_name} {i.variant_name}" for i in order.items.order_by("id")]
    return _clean(", ".join(parts), limit=300)


def _create(order, recipient_type, event, phone, params, dedupe_key):
    note, created = Notification.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "order": order,
            "recipient_type": recipient_type,
            "event": event,
            "recipient_phone": phone,
            "template_name": settings.WHATSAPP_TEMPLATE_NAMES[event],
            "params": params,
        },
    )
    return note.pk if created else None


def _dispatch_on_commit(ids):
    ids = [i for i in ids if i]
    if ids:
        transaction.on_commit(partial(tasks.dispatch_now, ids), robust=True)


def queue_order_created(order):
    """Call inside the checkout transaction. Rows commit (or roll back) together with the order."""
    customer = order.customer
    ids = [
        _create(
            order,
            Notification.Recipient.OWNER,
            Notification.Event.OWNER_NEW_ORDER,
            "",
            [
                _clean(order.reference),
                _clean(customer.name),
                _clean(customer.phone),
                _clean(order.delivery_area),
                _items_summary(order),
                _money(order.total),
            ],
            f"order:{order.pk}:owner:new",
        )
    ]
    if customer.whatsapp_opt_in:
        ids.append(
            _create(
                order,
                Notification.Recipient.CUSTOMER,
                Notification.Event.ORDER_RECEIVED,
                customer.phone,
                [_clean(customer.name), _clean(order.reference), _money(order.total), _clean(order.delivery_area)],
                f"order:{order.pk}:customer:received",
            )
        )
    _dispatch_on_commit(ids)


def queue_status_change(order, history):
    """Call inside the status-change transaction. Customer is told only if they consented."""
    event = EVENT_FOR_STATUS.get(history.new_status)
    customer = order.customer
    if not event or not customer.whatsapp_opt_in:
        return
    note_id = _create(
        order,
        Notification.Recipient.CUSTOMER,
        event,
        customer.phone,
        [_clean(customer.name), _clean(order.reference)],
        f"history:{history.pk}:customer",
    )
    _dispatch_on_commit([note_id])


def requeue(notification_ids):
    """Put FAILED / GAVE_UP notifications back in the outbox. Returns how many were re-queued."""
    now = timezone.now()
    return Notification.objects.filter(
        pk__in=list(notification_ids),
        status__in=[Notification.Status.FAILED, Notification.Status.GAVE_UP],
    ).update(
        status=Notification.Status.PENDING,
        attempts=0,
        next_attempt_at=now,
        last_error="",
        updated_at=now,
    )