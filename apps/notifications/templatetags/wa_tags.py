import re
from decimal import Decimal
from urllib.parse import quote

from django import template
from django.conf import settings
from django.urls import reverse

register = template.Library()


def money(value):
    s = f"{Decimal(value):,.2f}"
    return s[:-3] if s.endswith(".00") else s


def normalize_ke_phone(raw):
    """0748077609 / +254748077609 / 254748077609 -> 254748077609, else ''."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("254") and len(digits) == 12:
        number = digits
    elif digits.startswith("0") and len(digits) == 10:
        number = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "71":
        number = "254" + digits
    else:
        return ""
    return number if number[3] in "71" else ""


def _items(order):
    return "\n".join(
        f"{i.product_name} {i.variant_name} x {i.quantity} - KSh {money(i.line_total)}"
        for i in order.items.all()
    )


def _totals(order):
    lines = [f"Subtotal: KSh {money(order.subtotal)}"]
    if order.delivery_fee and order.delivery_fee > 0:
        lines.append(f"Delivery: KSh {money(order.delivery_fee)}")
    lines.append(f"TOTAL: KSh {money(order.total)}")
    return "\n".join(lines)


def build_message(order, tracking_url):
    name = order.customer.name
    ref = order.reference
    pay = order.get_payment_method_display()
    where = f"{order.delivery_area}, {order.delivery_address}"
    st = order.status

    if st == "NEW":
        return "Order received", (
            f"Hello {name},\n\nThank you for choosing Royal Cream Dairy!\n\n"
            f"We have received your order {ref}.\n\n"
            f"Our team is reviewing your order and will update you once it has been confirmed.\n\n"
            f"Follow your order here:\n{tracking_url}\n\nPure Goodness, Every Day."
        )
    if st == "CONFIRMED":
        return "Order confirmation receipt", (
            f"ROYAL CREAM DAIRY\nORDER CONFIRMATION RECEIPT\n\n"
            f"Order: {ref}\nDate: {order.created_at:%d %b %Y %H:%M}\n\n"
            f"Customer: {name}\nDelivery: {where}\n\nITEMS\n{_items(order)}\n\n"
            f"{_totals(order)}\n\nPayment: {pay}\nOrder Status: CONFIRMED\n\n"
            f"Track your order:\n{tracking_url}\n\nThank you for choosing Royal Cream Dairy."
        )
    if st == "PREPARING":
        return "Order is being prepared", (
            f"Hello {name},\n\nYour Royal Cream Dairy order {ref} is now being prepared.\n\n"
            f"We are getting your dairy products ready.\n\nOrder Total: KSh {money(order.total)}\n\n"
            f"Track your order:\n{tracking_url}"
        )
    if st == "OUT_FOR_DELIVERY":
        return "Out for delivery", (
            f"Good news, {name}!\n\nYour Royal Cream Dairy order {ref} is now OUT FOR DELIVERY.\n\n"
            f"Your order:\n{_items(order)}\n\nTotal: KSh {money(order.total)}\nPayment: {pay}\n\n"
            f"Delivery Location: {where}\n\nTrack your order:\n{tracking_url}\n\n"
            f"Thank you for choosing Royal Cream Dairy!"
        )
    if st == "COMPLETED":
        return "Delivery completion receipt", (
            f"ROYAL CREAM DAIRY\nDELIVERY COMPLETION RECEIPT\n\nOrder: {ref}\nCustomer: {name}\n\n"
            f"{_items(order)}\n\n{_totals(order)}\n\nPayment: {pay}\n"
            f"Delivery Status: COMPLETED\nCompleted: {order.updated_at:%d %b %Y %H:%M}\n\n"
            f"Thank you for choosing Royal Cream Dairy.\nPure Goodness, Every Day."
        )
    if st == "CANCELLED":
        return "Order cancelled", (
            f"Hello {name},\n\nYour Royal Cream Dairy order {ref} has been cancelled.\n"
            f"Please contact us if you have any questions."
        )
    return "", ""


@register.inclusion_tag("dashboard/_wa_panel.html", takes_context=True)
def wa_panel(context, order):
    request = context.get("request")
    path = reverse("order_confirmation", kwargs={"token": order.public_token})
    base = (getattr(settings, "PUBLIC_SITE_URL", "") or "").rstrip("/")
    if base:
        tracking_url = base + path
    elif request is not None:
        tracking_url = request.build_absolute_uri(path)
    else:
        tracking_url = path

    title, message = build_message(order, tracking_url)
    phone = normalize_ke_phone(order.customer.phone)
    wa_url = f"https://wa.me/{phone}?text={quote(message, safe='')}" if (phone and message) else ""
    return {
        "order": order,
        "title": title,
        "message": message,
        "phone": phone,
        "raw_phone": order.customer.phone,
        "wa_url": wa_url,
        "chat_url": f"https://wa.me/{phone}" if phone else "",
        "using_local_url": not base,
    }

EVENT_STATUS = {
    "ORDER_RECEIVED": "NEW",
    "ORDER_CONFIRMED": "CONFIRMED",
    "ORDER_OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
    "ORDER_COMPLETED": "COMPLETED",
    "ORDER_CANCELLED": "CANCELLED",
}


def _tracking_url(context, order):
    request = context.get("request")
    path = reverse("order_confirmation", kwargs={"token": order.public_token})
    base = (getattr(settings, "PUBLIC_SITE_URL", "") or "").rstrip("/")
    if base:
        return base + path
    return request.build_absolute_uri(path) if request is not None else path


@register.inclusion_tag("dashboard/_wa_alert.html", takes_context=True)
def wa_alert(context):
    """Completed orders (last 2 days) whose WhatsApp message is still waiting to be forwarded."""
    import json
    from datetime import timedelta

    from django.utils import timezone

    from apps.notifications.models import Notification

    request = context.get("request")
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {"items_json": "[]"}
    rows = (
        Notification.objects.filter(
            recipient_type="CUSTOMER",
            event="ORDER_COMPLETED",
            status="PENDING",
            order__customer__whatsapp_opt_in=True,
            created_at__gte=timezone.now() - timedelta(days=2),
        )
        .select_related("order", "order__customer")
        .order_by("-created_at")[:10]
    )
    seen, items = set(), []
    for n in rows:
        if n.order_id in seen:
            continue
        seen.add(n.order_id)
        items.append({
            "pk": n.order_id,
            "ref": n.order.reference,
            "name": n.order.customer.name,
            "url": "/owner/notifications/#wa-queue",
        })
    return {"items_json": json.dumps(items)}


@register.simple_tag(takes_context=True)
def wa_forward(context, n):
    """wa.me link for the message that belongs to this notification's event."""
    status = EVENT_STATUS.get(n.event)
    if n.recipient_type != "CUSTOMER" or not status:
        return ""
    order = n.order
    phone = normalize_ke_phone(order.customer.phone)
    if not phone:
        return ""
    original = order.status
    order.status = status
    try:
        _title, message = build_message(order, _tracking_url(context, order))
    finally:
        order.status = original
    return f"https://wa.me/{phone}?text={quote(message, safe='')}" if message else ""


@register.inclusion_tag("dashboard/_wa_queue.html", takes_context=True)
def wa_queue(context):
    """Orders that need a WhatsApp update: active orders and orders completed in the last 7 days."""
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone

    from apps.orders.models import Order

    request = context.get("request")
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {"items": []}
    active = ["NEW", "CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY"]
    qs = (
        Order.objects.filter(
            Q(status__in=active) | Q(status="COMPLETED", updated_at__gte=timezone.now() - timedelta(days=7))
        )
        .select_related("customer")
        .prefetch_related("items")
        .order_by("-updated_at")[:30]
    )
    items = []
    for o in qs:
        title, message = build_message(o, _tracking_url(context, o))
        phone = normalize_ke_phone(o.customer.phone)
        items.append({
            "order": o,
            "key": f"{o.pk}_{o.status}",
            "title": title,
            "message": message,
            "phone": phone,
            "raw_phone": o.customer.phone,
            "consent": o.customer.whatsapp_opt_in,
            "wa_url": f"https://wa.me/{phone}?text={quote(message, safe='')}" if (phone and message) else "",
            "chat_url": f"https://wa.me/{phone}" if phone else "",
        })
    return {"items": items}
