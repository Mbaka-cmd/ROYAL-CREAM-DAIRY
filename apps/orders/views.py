import json
import logging

from django.conf import settings
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from apps.catalogue.models import ProductVariant

from . import services
from .cart import price_cart
from .models import Order

logger = logging.getLogger(__name__)


def _checkout_rate(group, request):
    return settings.CHECKOUT_RATE_LIMIT


def _cart_rate(group, request):
    return settings.CART_VALIDATE_RATE_LIMIT


@require_POST
@ratelimit(key="ip", rate=_cart_rate, method="POST", block=False)
def cart_validate(request):
    if getattr(request, "limited", False):
        return JsonResponse({"error": "rate_limited"}, status=429)
    if len(request.body) > 20_000:
        return JsonResponse({"error": "too_large"}, status=413)
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "invalid_json"}, status=400)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return JsonResponse({"error": "invalid_items"}, status=400)
    return JsonResponse(price_cart(items))


def _render_checkout(request, *, form=None, error="", status=200):
    return render(request, "checkout/checkout.html", {"form": form or {}, "error": error}, status=status)


@require_http_methods(["GET", "POST"])
@ratelimit(key="ip", rate=_checkout_rate, method="POST", block=False)
def checkout(request):
    if request.method == "GET":
        return _render_checkout(request)

    data = request.POST
    form = {
        "name": data.get("name", ""),
        "phone": data.get("phone", ""),
        "delivery_area": data.get("delivery_area", ""),
        "delivery_address": data.get("delivery_address", ""),
        "delivery_instructions": data.get("delivery_instructions", ""),
        "whatsapp_consent": data.get("whatsapp_consent") == "on",
    }

    if getattr(request, "limited", False):
        logger.warning("Checkout rate limit hit")
        return _render_checkout(
            request,
            form=form,
            status=429,
            error="Too many order attempts. Please wait a few minutes and try again.",
        )

    if data.get("website"):
        logger.warning("Checkout honeypot triggered")
        return HttpResponseBadRequest("Bad request")

    key = data.get("idempotency_key", "").strip()
    if not key:
        return _render_checkout(
            request, form=form, status=400, error="Please reload the page and try again."
        )

    try:
        items = json.loads(data.get("cart", "[]"))
        if not isinstance(items, list):
            raise ValueError("cart must be a list")
    except ValueError:
        return _render_checkout(request, form=form, status=400, error="Your cart could not be read. Please reload the page.")

    try:
        order, _created = services.place_order(
            items=items,
            name=form["name"],
            phone=form["phone"],
            whatsapp_consent=form["whatsapp_consent"],
            delivery_area=form["delivery_area"],
            delivery_address=form["delivery_address"],
            delivery_instructions=form["delivery_instructions"],
            idempotency_key=key,
        )
    except services.CheckoutError as exc:
        logger.info("Checkout rejected: %s", exc)
        return _render_checkout(request, form=form, status=400, error=str(exc))
    except services.InsufficientStock as exc:
        logger.info("Checkout rejected: insufficient stock for variant %s", exc.variant_id)
        variant = ProductVariant.objects.select_related("product").filter(pk=exc.variant_id).first()
        label = f"{variant.product.name} {variant.name}" if variant else "An item"
        if exc.available > 0:
            message = f"Sorry, only {exc.available} of {label} left. Please update your cart."
        else:
            message = f"Sorry, {label} just sold out. Please update your cart."
        return _render_checkout(request, form=form, status=409, error=message)

    return redirect("order_confirmation", token=order.public_token)


@never_cache
@require_GET
def order_confirmation(request, token):
    order = get_object_or_404(
        Order.objects.select_related("customer").prefetch_related("items"),
        public_token=token,
    )
    purchase = {
        "transaction_id": order.reference,
        "currency": "KES",
        "value": float(order.total),
        "items": [
            {
                "item_id": str(item.variant_id),
                "item_name": f"{item.product_name} {item.variant_name}",
                "price": float(item.unit_price),
                "quantity": item.quantity,
            }
            for item in order.items.all()
        ],
    }
    return render(request, "checkout/confirmation.html", {"order": order, "ga_purchase": purchase})