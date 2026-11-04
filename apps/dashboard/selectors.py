from datetime import timedelta

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.catalogue.selectors import sellable_variants
from apps.inventory.models import Inventory
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderItem, OrderStatusHistory

S = Order.Status


def order_counts():
    counts = Order.objects.aggregate(
        new=Count("id", filter=Q(status=S.NEW)),
        confirmed=Count("id", filter=Q(status=S.CONFIRMED)),
        preparing=Count("id", filter=Q(status=S.PREPARING)),
        out_for_delivery=Count("id", filter=Q(status=S.OUT_FOR_DELIVERY)),
        delivery_failed=Count("id", filter=Q(status=S.DELIVERY_FAILED)),
    )
    counts["completed_today"] = OrderStatusHistory.objects.filter(
        new_status=S.COMPLETED, created_at__date=timezone.localdate()
    ).count()
    return counts


def stock_counts():
    out = sellable_variants().filter(available__lte=0).count()
    low = (
        Inventory.objects.filter(variant__is_active=True, variant__product__is_active=True)
        .annotate(av=F("quantity_on_hand") - F("quantity_reserved"))
        .filter(av__gt=0, av__lte=F("low_stock_threshold"))
        .count()
    )
    return {"low": low, "out": out}


def notification_counts():
    now = timezone.now()
    return {
        "needs_review": Notification.objects.filter(
            status__in=[Notification.Status.FAILED, Notification.Status.GAVE_UP]
        ).count(),
        "unsent": Notification.objects.filter(
            status=Notification.Status.PENDING, created_at__lt=now - timedelta(minutes=15)
        ).count(),
    }


def _completed(start, end):
    return OrderStatusHistory.objects.filter(
        new_status=S.COMPLETED, created_at__date__gte=start, created_at__date__lte=end
    )


def sales_by_day(start, end):
    return list(
        _completed(start, end)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(orders=Count("order_id", distinct=True), revenue=Sum("order__total"))
        .order_by("-day")
    )


def sales_totals(start, end):
    totals = _completed(start, end).aggregate(
        orders=Count("order_id", distinct=True), revenue=Sum("order__total")
    )
    totals["revenue"] = totals["revenue"] or 0
    return totals


def top_products(start, end, limit=10):
    return list(
        OrderItem.objects.filter(
            order__status=S.COMPLETED,
            order__status_history__new_status=S.COMPLETED,
            order__status_history__created_at__date__gte=start,
            order__status_history__created_at__date__lte=end,
        )
        .values("product_name", "variant_name")
        .annotate(units=Sum("quantity"), revenue=Sum("line_total"))
        .order_by("-units", "product_name")[:limit]
    )