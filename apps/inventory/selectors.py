from django.db.models import F

from .models import Inventory


def low_stock_items():
    return (
        Inventory.objects.select_related("variant__product")
        .annotate(available_qty=F("quantity_on_hand") - F("quantity_reserved"))
        .filter(available_qty__lte=F("low_stock_threshold"))
        .order_by("available_qty")
    )