from datetime import timedelta

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.notifications.models import Notification
from apps.orders.models import Order

from .models import Customer

ANON_NAME = "Anonymised customer"
ANON_PREFIX = "anon-"
CLOSED_STATUSES = [Order.Status.COMPLETED, Order.Status.CANCELLED]


class OpenOrdersError(Exception):
    """The customer still has an order in progress."""


def anonymize_customer(customer):
    """Remove a customer's personal details but keep order totals for the business records.

    Returns True if details were removed, False if already anonymised.
    Raises OpenOrdersError if any order is still in progress.
    """
    with transaction.atomic():
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
        if customer.phone.startswith(ANON_PREFIX):
            return False
        if customer.orders.exclude(status__in=CLOSED_STATUSES).exists():
            raise OpenOrdersError()
        customer.orders.update(delivery_address="", delivery_instructions="")
        notes = Notification.objects.filter(order__customer=customer)
        notes.filter(status__in=[Notification.Status.PENDING, Notification.Status.SENDING]).update(
            status=Notification.Status.SKIPPED, last_error="Customer data removed"
        )
        notes.update(params=[], recipient_phone="")
        customer.name = ANON_NAME
        customer.phone = f"{ANON_PREFIX}{customer.pk}"
        customer.whatsapp_opt_in = False
        customer.whatsapp_consent_at = None
        customer.save()
    return True


def customers_due_for_purge(months, now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(days=30 * months)
    return (
        Customer.objects.exclude(phone__startswith=ANON_PREFIX)
        .annotate(last_order=Max("orders__created_at"))
        .filter(Q(last_order__lt=cutoff) | Q(last_order__isnull=True, created_at__lt=cutoff))
    )