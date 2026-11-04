from collections.abc import Mapping

from django.db import transaction

from apps.catalogue.models import ProductVariant

from .models import Inventory, StockMovement


class InventoryError(Exception):
    """Base class for inventory rule violations."""


class InsufficientStock(InventoryError):
    def __init__(self, variant_id, requested, available):
        self.variant_id = variant_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient stock for variant {variant_id}: requested {requested}, available {available}."
        )


def _check_quantity(quantity):
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise InventoryError("Quantity must be a positive whole number.")


def _check_items(items):
    if not isinstance(items, Mapping) or not items:
        raise InventoryError("No items given.")
    for quantity in items.values():
        _check_quantity(quantity)


def _log(variant_id, movement_type, quantity, *, reference="", reason="", user=None):
    StockMovement.objects.create(
        variant_id=variant_id,
        movement_type=movement_type,
        quantity=quantity,
        reference=reference,
        reason=reason,
        created_by=user,
    )


def _lock_many(variant_ids):
    """Lock inventory rows in ascending variant id order (consistent order avoids deadlocks)."""
    ids = sorted(set(variant_ids))
    rows = Inventory.objects.select_for_update().filter(variant_id__in=ids).order_by("variant_id")
    return {row.variant_id: row for row in rows}


def _locked_one(variant_id):
    if not ProductVariant.objects.filter(pk=variant_id).exists():
        raise InventoryError(f"Unknown variant {variant_id}.")
    Inventory.objects.get_or_create(variant_id=variant_id)
    return Inventory.objects.select_for_update().get(variant_id=variant_id)


def receive_stock(variant_id, quantity, *, reference="", reason="Stock received", user=None):
    _check_quantity(quantity)
    with transaction.atomic():
        row = _locked_one(variant_id)
        row.quantity_on_hand += quantity
        row.save(update_fields=["quantity_on_hand", "updated_at"])
        _log(variant_id, StockMovement.Type.RECEIVE, quantity, reference=reference, reason=reason, user=user)
    return row


def adjust_stock(variant_id, delta, *, reason, user=None):
    if isinstance(delta, bool) or not isinstance(delta, int) or delta == 0:
        raise InventoryError("Adjustment must be a non-zero whole number.")
    reason = (reason or "").strip()
    if not reason:
        raise InventoryError("A reason is required for stock adjustments.")
    with transaction.atomic():
        row = _locked_one(variant_id)
        new_on_hand = row.quantity_on_hand + delta
        if new_on_hand < row.quantity_reserved:
            raise InventoryError("Adjustment would take stock below the quantity reserved for open orders.")
        row.quantity_on_hand = new_on_hand
        row.save(update_fields=["quantity_on_hand", "updated_at"])
        _log(variant_id, StockMovement.Type.ADJUST, delta, reason=reason, user=user)
    return row


def record_waste(variant_id, quantity, *, reason, user=None):
    _check_quantity(quantity)
    reason = (reason or "").strip()
    if not reason:
        raise InventoryError("A reason is required to record waste.")
    with transaction.atomic():
        row = _locked_one(variant_id)
        if row.quantity_on_hand - quantity < row.quantity_reserved:
            raise InventoryError("Waste would take stock below the quantity reserved for open orders.")
        row.quantity_on_hand -= quantity
        row.save(update_fields=["quantity_on_hand", "updated_at"])
        _log(variant_id, StockMovement.Type.WASTE, quantity, reason=reason, user=user)
    return row


def reserve_stock(items, *, reference, user=None):
    """items: {variant_id: quantity}. All-or-nothing."""
    _check_items(items)
    with transaction.atomic():
        locked = _lock_many(items.keys())
        for variant_id in sorted(items):
            row = locked.get(variant_id)
            available = row.available if row else 0
            if items[variant_id] > available:
                raise InsufficientStock(variant_id, items[variant_id], available)
        for variant_id in sorted(items):
            row = locked[variant_id]
            row.quantity_reserved += items[variant_id]
            row.save(update_fields=["quantity_reserved", "updated_at"])
            _log(variant_id, StockMovement.Type.RESERVE, items[variant_id], reference=reference, user=user)


def release_reservation(items, *, reference, user=None, reason=""):
    _check_items(items)
    with transaction.atomic():
        locked = _lock_many(items.keys())
        for variant_id in sorted(items):
            row = locked.get(variant_id)
            if row is None or row.quantity_reserved < items[variant_id]:
                raise InventoryError(f"Cannot release {items[variant_id]} for variant {variant_id}: not reserved.")
        for variant_id in sorted(items):
            row = locked[variant_id]
            row.quantity_reserved -= items[variant_id]
            row.save(update_fields=["quantity_reserved", "updated_at"])
            _log(variant_id, StockMovement.Type.RELEASE, items[variant_id], reference=reference, reason=reason, user=user)


def fulfil_sale(items, *, reference, user=None):
    """Delivered: reduce on-hand and reserved by the same quantity."""
    _check_items(items)
    with transaction.atomic():
        locked = _lock_many(items.keys())
        for variant_id in sorted(items):
            row = locked.get(variant_id)
            if row is None or row.quantity_reserved < items[variant_id]:
                raise InventoryError(f"Cannot complete sale of {items[variant_id]} for variant {variant_id}: not reserved.")
        for variant_id in sorted(items):
            row = locked[variant_id]
            row.quantity_on_hand -= items[variant_id]
            row.quantity_reserved -= items[variant_id]
            row.save(update_fields=["quantity_on_hand", "quantity_reserved", "updated_at"])
            _log(variant_id, StockMovement.Type.SALE, items[variant_id], reference=reference, user=user)