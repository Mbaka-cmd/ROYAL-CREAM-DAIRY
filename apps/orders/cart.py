from decimal import Decimal

from apps.catalogue.selectors import sellable_variants

from .services import MAX_DISTINCT_ITEMS, MAX_ITEM_QUANTITY, _delivery_fee


def _money(value):
    return f"{value:.2f}"


def price_cart(raw_items):
    """Price a cart from database values only. Client-supplied prices are never read."""
    wanted = {}
    for raw in list(raw_items)[: MAX_DISTINCT_ITEMS * 2]:
        try:
            variant_id = int(raw["variant_id"])
            quantity = int(raw["quantity"])
        except (KeyError, TypeError, ValueError):
            continue
        if quantity < 1:
            continue
        wanted[variant_id] = wanted.get(variant_id, 0) + quantity
    wanted = dict(list(wanted.items())[:MAX_DISTINCT_ITEMS])

    variants = {v.id: v for v in sellable_variants().filter(id__in=list(wanted))}
    unavailable = [variant_id for variant_id in wanted if variant_id not in variants]

    lines = []
    subtotal = Decimal("0.00")
    valid = bool(variants) and not unavailable
    for variant_id, quantity in wanted.items():
        variant = variants.get(variant_id)
        if variant is None:
            continue
        cap = max(min(variant.available, MAX_ITEM_QUANTITY), 0)
        message = ""
        if cap == 0:
            message = "Out of stock"
        elif quantity > cap:
            message = f"Only {cap} available"
        ok = not message
        if not ok:
            valid = False
        line_total = variant.price * quantity
        subtotal += line_total
        lines.append(
            {
                "variant_id": variant.id,
                "product": variant.product.name,
                "variant": variant.name,
                "unit_price": _money(variant.price),
                "quantity": quantity,
                "line_total": _money(line_total),
                "available": cap,
                "ok": ok,
                "message": message,
            }
        )

    fee = _delivery_fee()
    return {
        "lines": lines,
        "unavailable": unavailable,
        "subtotal": _money(subtotal),
        "delivery_fee": _money(fee),
        "total": _money(subtotal + fee),
        "valid": valid,
    }