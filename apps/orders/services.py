import logging
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalogue.models import ProductVariant
from apps.customers.services import InvalidPhone, normalize_ke_phone, upsert_customer
from apps.delivery.selectors import active_zones, zone_by_id
from apps.inventory import services as inventory
from apps.notifications import services as notifications
from apps.inventory.services import InsufficientStock  # noqa: F401  (re-exported for views)

from .models import Order, OrderItem, OrderStatusHistory

logger = logging.getLogger(__name__)

MAX_ITEM_QUANTITY = 50
MAX_DISTINCT_ITEMS = 30

ALLOWED_TRANSITIONS = {
    Order.Status.NEW: {Order.Status.CONFIRMED, Order.Status.CANCELLED},
    Order.Status.CONFIRMED: {Order.Status.PREPARING, Order.Status.CANCELLED},
    Order.Status.PREPARING: {Order.Status.OUT_FOR_DELIVERY, Order.Status.CANCELLED},
    Order.Status.OUT_FOR_DELIVERY: {Order.Status.COMPLETED, Order.Status.DELIVERY_FAILED},
    Order.Status.DELIVERY_FAILED: {Order.Status.OUT_FOR_DELIVERY, Order.Status.CANCELLED},
    Order.Status.COMPLETED: set(),
    Order.Status.CANCELLED: set(),
}


class CheckoutError(Exception):
    """Invalid checkout input. Message is safe to show to the customer."""


class InvalidTransition(Exception):
    """Order status change not allowed."""


def _clean_items(items):
    merged = {}
    for raw in items or []:
        try:
            variant_id = int(raw["variant_id"])
            quantity = int(raw["quantity"])
        except (KeyError, TypeError, ValueError):
            raise CheckoutError("Invalid cart item.")
        if quantity < 1:
            raise CheckoutError("Quantity must be at least 1.")
        merged[variant_id] = merged.get(variant_id, 0) + quantity
    if not merged:
        raise CheckoutError("Your cart is empty.")
    if len(merged) > MAX_DISTINCT_ITEMS:
        raise CheckoutError("Too many different items in one order.")
    if any(q > MAX_ITEM_QUANTITY for q in merged.values()):
        raise CheckoutError(f"You can order at most {MAX_ITEM_QUANTITY} of one item.")
    return merged


def _delivery_fee(zone=None):
    """Fee for a delivery zone, or the flat DELIVERY_FEE setting when no zone applies."""
    if zone is not None:
        return Decimal(zone.fee).quantize(Decimal("0.01"))
    return Decimal(str(getattr(settings, "DELIVERY_FEE", "0.00"))).quantize(Decimal("0.01"))


def below_minimum_message(zone, subtotal):
    """Customer-safe message when the subtotal is under the zone's minimum order, else empty."""
    if zone is not None and zone.min_order > 0 and subtotal < zone.min_order:
        minimum = f"{zone.min_order:.2f}".removesuffix(".00")
        return f"The minimum order for {zone.name} is KSh {minimum}."
    return ""


def _resolve_zone(zone_id):
    """None while no zones are configured (free-text area). Otherwise a valid active zone is required."""
    if not active_zones().exists():
        return None
    zone = zone_by_id(zone_id)
    if zone is None:
        raise CheckoutError("Please choose your delivery area.")
    return zone


def place_order(
    *,
    items,
    name,
    phone,
    whatsapp_consent,
    delivery_area,
    delivery_address,
    idempotency_key,
    delivery_instructions="",
    delivery_zone_id=None,
):
    """Create an order. Prices always come from the database, never from the client.

    Returns (order, created). A repeated idempotency key returns the original order.
    Raises CheckoutError (bad input) or InsufficientStock.
    """
    key = (idempotency_key or "").strip()
    if not key or len(key) > 64:
        raise CheckoutError("Missing or invalid checkout key.")

    existing = Order.objects.filter(idempotency_key=key).first()
    if existing:
        return existing, False

    cart = _clean_items(items)
    name = (name or "").strip()
    delivery_area = (delivery_area or "").strip()
    delivery_address = (delivery_address or "").strip()
    delivery_instructions = (delivery_instructions or "").strip()
    if not 2 <= len(name) <= 150:
        raise CheckoutError("Please enter your name.")
    zone = _resolve_zone(delivery_zone_id)
    if zone is not None:
        delivery_area = zone.name
    if not 1 <= len(delivery_area) <= 100:
        raise CheckoutError("Please enter your delivery area.")
    if not 3 <= len(delivery_address) <= 255:
        raise CheckoutError("Please enter a specific delivery address.")
    if len(delivery_instructions) > 255:
        raise CheckoutError("Delivery instructions are too long.")
    try:
        normalize_ke_phone(phone)
    except InvalidPhone as exc:
        raise CheckoutError(str(exc))

    try:
        with transaction.atomic():
            order = _create_order(
                cart=cart,
                name=name,
                phone=phone,
                whatsapp_consent=whatsapp_consent,
                delivery_area=delivery_area,
                delivery_address=delivery_address,
                delivery_instructions=delivery_instructions,
                key=key,
                zone=zone,
            )
    except IntegrityError:
        existing = Order.objects.filter(idempotency_key=key).first()
        if existing:
            return existing, False
        raise

    logger.info("Order created: %s", order.reference)
    return order, True


def _create_order(
    *, cart, name, phone, whatsapp_consent, delivery_area, delivery_address, delivery_instructions, key, zone=None
):
    variants = {
        v.id: v
        for v in ProductVariant.objects.select_related("product").filter(
            id__in=cart.keys(), is_active=True, product__is_active=True, product__category__is_active=True
        )
    }
    if len(variants) != len(cart):
        raise CheckoutError("One or more products are no longer available.")

    subtotal = Decimal("0.00")
    lines = []
    for variant_id, quantity in cart.items():
        variant = variants[variant_id]
        line_total = variant.price * quantity
        subtotal += line_total
        lines.append((variant, quantity, line_total))
    message = below_minimum_message(zone, subtotal)
    if message:
        raise CheckoutError(message)
    delivery_fee = _delivery_fee(zone)

    customer = upsert_customer(name=name, phone=phone, whatsapp_consent=whatsapp_consent)

    order = Order.objects.create(
        reference=f"TMP-{uuid.uuid4().hex}",
        idempotency_key=key,
        customer=customer,
        delivery_area=delivery_area,
        delivery_address=delivery_address,
        delivery_instructions=delivery_instructions,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total=subtotal + delivery_fee,
    )
    order.reference = f"RC-{timezone.localtime().year}-{order.pk:05d}"
    order.save(update_fields=["reference", "updated_at"])

    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                variant=variant,
                product_name=variant.product.name,
                variant_name=variant.name,
                unit_price=variant.price,
                quantity=quantity,
                line_total=line_total,
            )
            for variant, quantity, line_total in lines
        ]
    )

    inventory.reserve_stock(cart, reference=order.reference)

    OrderStatusHistory.objects.create(order=order, old_status="", new_status=Order.Status.NEW, note="Order placed")

    notifications.queue_order_created(order)
    return order


def change_status(order_id, new_status, *, user=None, note=""):
    """The only supported way to change an order's status."""
    if new_status not in Order.Status.values:
        raise InvalidTransition(f"Unknown status: {new_status}")
    note = (note or "").strip()

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        old_status = order.status
        if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
            raise InvalidTransition(f"Cannot change order from {old_status} to {new_status}.")
        if new_status == Order.Status.CANCELLED and not note:
            raise InvalidTransition("A reason is required to cancel an order.")

        items = {item.variant_id: item.quantity for item in order.items.all()}
        if new_status == Order.Status.COMPLETED:
            inventory.fulfil_sale(items, reference=order.reference, user=user)
        elif new_status == Order.Status.CANCELLED:
            inventory.release_reservation(items, reference=order.reference, user=user, reason=note)
            order.cancel_reason = note

        order.status = new_status
        order.save(update_fields=["status", "cancel_reason", "updated_at"])
        history = OrderStatusHistory.objects.create(
            order=order, old_status=old_status, new_status=new_status, note=note, changed_by=user
        )
        notifications.queue_status_change(order, history)

    logger.info("Order %s: %s -> %s", order.reference, old_status, new_status)
    return order
