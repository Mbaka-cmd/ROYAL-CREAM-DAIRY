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

# ---------- overview additions ----------
def _trend(cur, prev):
    cur = float(cur or 0)
    prev = float(prev or 0)
    if prev == 0:
        if cur == 0:
            return {"dir": "flat", "label": "No data yesterday"}
        return {"dir": "up", "label": "New vs yesterday"}
    pct = round((cur - prev) / prev * 100)
    if pct == 0:
        return {"dir": "flat", "label": "Same as yesterday"}
    return {"dir": "up" if pct > 0 else "down", "label": f"{pct:+d}% vs yesterday"}


def _placed(day):
    agg = (
        Order.objects.filter(created_at__date=day)
        .exclude(status=S.CANCELLED)
        .aggregate(n=Count("id"), total=Sum("total"))
    )
    n = agg["n"] or 0
    total = agg["total"] or 0
    return n, (total / n if n else 0)


def kpis():
    today = timezone.localdate()
    yday = today - timedelta(days=1)
    sales_t = sales_totals(today, today)["revenue"]
    sales_y = sales_totals(yday, yday)["revenue"]
    n_t, avg_t = _placed(today)
    n_y, avg_y = _placed(yday)
    return {
        "sales": {"value": sales_t, "trend": _trend(sales_t, sales_y)},
        "orders": {"value": n_t, "trend": _trend(n_t, n_y)},
        "avg": {"value": avg_t, "trend": _trend(avg_t, avg_y)},
    }


def stale_new_count(minutes=15):
    cutoff = timezone.now() - timedelta(minutes=minutes)
    return Order.objects.filter(status=S.NEW, created_at__lt=cutoff).count()


def sales_week():
    today = timezone.localdate()
    start = today - timedelta(days=6)
    rows = {r["day"]: r for r in sales_by_day(start, today)}
    days = [start + timedelta(days=i) for i in range(7)]
    vals = [float(rows[d]["revenue"] or 0) if d in rows else 0.0 for d in days]
    counts = [rows[d]["orders"] if d in rows else 0 for d in days]
    top = max(vals) or 1
    bars = []
    for i, d in enumerate(days):
        h = int(vals[i] / top * 150)
        if vals[i] > 0 and h < 4:
            h = 4
        bars.append(
            {
                "x": 30 + i * 95,
                "cx": 60 + i * 95,
                "y": 180 - h,
                "vy": 172 - h,
                "h": h,
                "label": d.strftime("%a"),
                "value": int(vals[i]),
                "orders": counts[i],
                "today": d == today,
            }
        )
    return {"bars": bars, "total": sum(vals), "orders": sum(counts)}
