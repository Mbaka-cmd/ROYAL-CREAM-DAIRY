import logging
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, IntegerField, Q, Value
from django.db.models.functions import Coalesce
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.catalogue.models import Product, ProductVariant
from apps.customers.models import Customer
from apps.customers.services import InvalidPhone, normalize_ke_phone
from apps.inventory import services as inventory
from apps.inventory.models import StockMovement
from apps.notifications import services as notification_services
from apps.notifications.models import Notification
from apps.orders import services as order_services
from apps.orders.models import Order

from . import selectors
from .forms import ProductForm, StockActionForm, VariantFormSet
from .permissions import staff_view

logger = logging.getLogger(__name__)

ACTION_LABELS = {
    "CONFIRMED": "Confirm order",
    "PREPARING": "Start preparing",
    "OUT_FOR_DELIVERY": "Out for delivery",
    "COMPLETED": "Mark delivered",
    "DELIVERY_FAILED": "Delivery failed",
}

NOTIFICATION_FILTERS = {
    "review": [Notification.Status.FAILED, Notification.Status.GAVE_UP],
    "pending": [Notification.Status.PENDING, Notification.Status.SENDING],
    "sent": [Notification.Status.SENT, Notification.Status.DELIVERED, Notification.Status.READ],
}


def _page(request, queryset, per_page):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


# ---------------- home ----------------
@staff_view()
def home(request):
    user = request.user
    hour = timezone.localtime().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    context = {
        "orders": None, "stock": None, "notifications": None, "recent_orders": [],
        "kpis": None, "chart": None, "attention": [], "greeting": greeting,
        "today": timezone.localdate(),
    }
    attention = []
    orders_url = reverse("owner_orders")
    if user.has_perm("orders.view_order"):
        counts = selectors.order_counts()
        context["orders"] = counts
        context["recent_orders"] = Order.objects.select_related("customer")[:8]
        context["kpis"] = selectors.kpis()
        context["chart"] = selectors.sales_week()
        stale = selectors.stale_new_count()
        if stale:
            attention.append(("alert", f"{stale} new order(s) waiting more than 15 minutes", f"{orders_url}?status=NEW"))
        if counts["delivery_failed"]:
            attention.append(("alert", f"{counts['delivery_failed']} failed delivery(ies) to follow up", f"{orders_url}?status=DELIVERY_FAILED"))
    if user.has_perm("inventory.view_inventory"):
        stock = selectors.stock_counts()
        context["stock"] = stock
        if stock["out"]:
            attention.append(("alert", f"{stock['out']} product(s) out of stock", reverse("owner_inventory") + "?filter=out"))
        if stock["low"]:
            attention.append(("warn", f"{stock['low']} product(s) running low", reverse("owner_inventory") + "?filter=low"))
    if user.has_perm("notifications.view_notification"):
        notes = selectors.notification_counts()
        context["notifications"] = notes
        if notes["needs_review"]:
            attention.append(("alert", f"{notes['needs_review']} WhatsApp message(s) need review", reverse("owner_notifications") + "?status=review"))
        if notes["unsent"]:
            attention.append(("warn", f"{notes['unsent']} WhatsApp message(s) unsent for 15+ minutes", reverse("owner_notifications") + "?status=pending"))
    context["attention"] = [{"level": l, "text": x, "url": u} for l, x, u in attention]
    return render(request, "dashboard/home.html", context)


# ---------------- instant search ----------------
@staff_view()
@ratelimit(key="user", rate="120/m", method="GET", block=True)
def search(request):
    q = request.GET.get("q", "").strip()[:50]
    out = {"orders": [], "customers": [], "products": []}
    if len(q) < 2:
        return JsonResponse(out)
    user = request.user
    can_orders = user.has_perm("orders.view_order")
    phone_part = q.lstrip("0+") if q.replace("+", "").isdigit() else ""
    if can_orders:
        cond = Q(reference__icontains=q) | Q(customer__name__icontains=q) | Q(customer__phone__icontains=q)
        if phone_part:
            cond |= Q(customer__phone__icontains=phone_part)
        try:
            cond |= Q(customer__phone=normalize_ke_phone(q))
        except InvalidPhone:
            pass
        for o in Order.objects.select_related("customer").filter(cond)[:6]:
            out["orders"].append({
                "title": o.reference,
                "sub": f"{o.customer.name} - {o.customer.phone} - KSh {int(o.total)}",
                "badge": o.get_status_display(),
                "url": reverse("owner_order_detail", args=[o.pk]),
            })
    if can_orders and user.has_perm("customers.view_customer"):
        ccond = Q(name__icontains=q) | Q(phone__icontains=q)
        if phone_part:
            ccond |= Q(phone__icontains=phone_part)
        for c in Customer.objects.filter(ccond)[:5]:
            out["customers"].append({
                "title": c.name,
                "sub": c.phone,
                "badge": "",
                "url": reverse("owner_orders") + "?" + urlencode({"q": c.phone}),
            })
    if user.has_perm("catalogue.view_product"):
        for p in Product.objects.filter(name__icontains=q)[:5]:
            if user.has_perm("catalogue.change_product"):
                url = reverse("owner_product_update", args=[p.pk])
            else:
                url = reverse("owner_products") + "?" + urlencode({"q": p.name})
            out["products"].append({"title": p.name, "sub": "Product", "badge": "Active" if p.is_active else "Hidden", "url": url})
    return JsonResponse(out)


# ---------------- orders ----------------
@staff_view("orders.view_order")
def order_list(request):
    queryset = Order.objects.select_related("customer")
    status = request.GET.get("status", "")
    if status in Order.Status.values:
        queryset = queryset.filter(status=status)
    else:
        status = ""
    q = request.GET.get("q", "").strip()[:50]
    if q:
        condition = Q(reference__icontains=q) | Q(customer__name__icontains=q)
        try:
            condition |= Q(customer__phone=normalize_ke_phone(q))
        except InvalidPhone:
            pass
        queryset = queryset.filter(condition)
    filters = {k: v for k, v in (("status", status), ("q", q)) if v}
    return render(
        request,
        "dashboard/orders.html",
        {
            "page": _page(request, queryset, 20),
            "statuses": Order.Status.choices,
            "active_status": status,
            "q": q,
            "filter_qs": urlencode(filters),
        },
    )


@staff_view("orders.view_order")
def order_detail(request, pk):
    order = get_object_or_404(
        Order.objects.select_related("customer").prefetch_related(
            "items", "status_history__changed_by", "notifications"
        ),
        pk=pk,
    )
    allowed = order_services.ALLOWED_TRANSITIONS.get(order.status, set())
    transitions = [
        (value, ACTION_LABELS.get(value, value))
        for value in Order.Status.values
        if value in allowed and value != Order.Status.CANCELLED
    ]
    return render(
        request,
        "dashboard/order_detail.html",
        {
            "order": order,
            "transitions": transitions,
            "can_cancel": Order.Status.CANCELLED in allowed,
            "retryable": (Notification.Status.FAILED, Notification.Status.GAVE_UP),
        },
    )


@staff_view("orders.change_order")
@require_POST
def order_status(request, pk):
    new_status = request.POST.get("status", "")
    note = request.POST.get("note", "")
    try:
        order = order_services.change_status(pk, new_status, user=request.user, note=note)
    except Order.DoesNotExist:
        raise Http404
    except (order_services.InvalidTransition, inventory.InventoryError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Order {order.reference} is now {order.get_status_display()}.")
    return redirect("owner_order_detail", pk=pk)


# ---------------- inventory ----------------
def _inventory_queryset():
    return (
        ProductVariant.objects.select_related("product")
        .filter(is_active=True, product__is_active=True)
        .annotate(
            on_hand=Coalesce(F("inventory__quantity_on_hand"), Value(0), output_field=IntegerField()),
            reserved=Coalesce(F("inventory__quantity_reserved"), Value(0), output_field=IntegerField()),
            threshold=Coalesce(F("inventory__low_stock_threshold"), Value(5), output_field=IntegerField()),
        )
        .annotate(available=F("on_hand") - F("reserved"))
        .order_by("product__name", "name")
    )


def _render_inventory(request, form, status=200):
    queryset = _inventory_queryset()
    stock_filter = request.GET.get("filter", "")
    if stock_filter == "low":
        queryset = queryset.filter(available__gt=0, available__lte=F("threshold"))
    elif stock_filter == "out":
        queryset = queryset.filter(available__lte=0)
    else:
        stock_filter = ""
    page = _page(request, queryset, 50)
    rows = list(page.object_list)
    for row in rows:
        if row.available <= 0:
            row.stock_status = "Out of stock"
        elif row.available <= row.threshold:
            row.stock_status = "Low stock"
        else:
            row.stock_status = "In stock"
    movements = StockMovement.objects.select_related("variant__product", "created_by")[:30]
    return render(
        request,
        "dashboard/inventory.html",
        {"page": page, "rows": rows, "form": form, "movements": movements, "active_filter": stock_filter},
        status=status,
    )


@staff_view("inventory.view_inventory")
def inventory_list(request):
    initial = {}
    variant_id = request.GET.get("variant", "")
    if variant_id.isdigit():
        initial["variant"] = int(variant_id)
    return _render_inventory(request, StockActionForm(initial=initial))


@staff_view("inventory.change_inventory")
@require_POST
def inventory_adjust(request):
    form = StockActionForm(request.POST)
    if not form.is_valid():
        return _render_inventory(request, form, status=400)
    variant = form.cleaned_data["variant"]
    action = form.cleaned_data["action"]
    quantity = form.cleaned_data["quantity"]
    reason = (form.cleaned_data["reason"] or "").strip()
    try:
        if action == "receive":
            inventory.receive_stock(variant.id, quantity, reason=reason or "Stock received", user=request.user)
        elif action == "adjust_up":
            inventory.adjust_stock(variant.id, quantity, reason=reason, user=request.user)
        elif action == "adjust_down":
            inventory.adjust_stock(variant.id, -quantity, reason=reason, user=request.user)
        else:
            inventory.record_waste(variant.id, quantity, reason=reason, user=request.user)
    except inventory.InventoryError as exc:
        form.add_error(None, str(exc))
        return _render_inventory(request, form, status=400)
    messages.success(request, f"Stock updated for {variant}.")
    return redirect("owner_inventory")


# ---------------- products ----------------
@staff_view("catalogue.view_product")
def product_list(request):
    queryset = Product.objects.select_related("category").prefetch_related("variants")
    q = request.GET.get("q", "").strip()[:50]
    if q:
        queryset = queryset.filter(name__icontains=q)
    return render(
        request,
        "dashboard/products.html",
        {"page": _page(request, queryset, 25), "q": q, "filter_qs": urlencode({"q": q} if q else {})},
    )


def _product_page(request, form, formset, product, status=200, save_error=""):
    return render(
        request,
        "dashboard/product_form.html",
        {"form": form, "formset": formset, "product": product, "save_error": save_error},
        status=status,
    )


@staff_view("catalogue.add_product", "catalogue.add_productvariant")
def product_create(request):
    form = ProductForm(request.POST or None, request.FILES or None)
    formset = VariantFormSet(request.POST or None, instance=form.instance)
    if request.method == "POST":
        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    product = form.save()
                    formset.instance = product
                    formset.save()
            except IntegrityError:
                return _product_page(
                    request, form, formset, None, 400, "Could not save: two sizes have the same name."
                )
            messages.success(request, f"Product '{product.name}' created. Receive stock to make it orderable.")
            return redirect("owner_products")
        return _product_page(request, form, formset, None, 400)
    return _product_page(request, form, formset, None)


@staff_view("catalogue.change_product", "catalogue.change_productvariant")
def product_update(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    formset = VariantFormSet(request.POST or None, instance=product)
    if request.method == "POST":
        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    form.save()
                    formset.save()
            except IntegrityError:
                return _product_page(
                    request, form, formset, product, 400, "Could not save: two sizes have the same name."
                )
            for variant_form in formset.forms:
                old_price = variant_form.initial.get("price")
                if old_price is not None and "price" in variant_form.changed_data:
                    logger.info(
                        "Variant price changed: user=%s variant=%s %s -> %s",
                        request.user.pk,
                        variant_form.instance.pk,
                        old_price,
                        variant_form.cleaned_data.get("price"),
                    )
            messages.success(request, f"Product '{product.name}' saved.")
            return redirect("owner_products")
        return _product_page(request, form, formset, product, 400)
    return _product_page(request, form, formset, product)


# ---------------- notifications ----------------
@staff_view("notifications.view_notification")
def notification_list(request):
    queryset = Notification.objects.select_related("order")
    status = request.GET.get("status", "")
    if status in NOTIFICATION_FILTERS:
        queryset = queryset.filter(status__in=NOTIFICATION_FILTERS[status])
    elif status in Notification.Status.values:
        queryset = queryset.filter(status=status)
    else:
        status = ""
    return render(
        request,
        "dashboard/notifications.html",
        {
            "page": _page(request, queryset, 25),
            "active_status": status,
            "filter_qs": urlencode({"status": status} if status else {}),
            "retryable": (Notification.Status.FAILED, Notification.Status.GAVE_UP),
        },
    )


@staff_view("notifications.change_notification")
@require_POST
def notification_retry(request, pk):
    count = notification_services.requeue([pk])
    if count:
        messages.success(request, "Notification re-queued. It will be sent on the next run.")
    else:
        messages.warning(request, "No notifications were re-queued (only failed ones can be retried).")
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = "owner_notifications"
    return redirect(target)


# ---------------- reports ----------------
def _parse_date(value, default):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return default


@staff_view("orders.view_order")
def reports(request):
    today = timezone.localdate()
    end = _parse_date(request.GET.get("end"), today)
    start = _parse_date(request.GET.get("start"), end - timedelta(days=29))
    if start > end:
        start, end = end, start
    if (end - start).days > 366:
        start = end - timedelta(days=366)
    return render(
        request,
        "dashboard/reports.html",
        {
            "start": start,
            "end": end,
            "daily": selectors.sales_by_day(start, end),
            "totals": selectors.sales_totals(start, end),
            "top": selectors.top_products(start, end),
        },
    )