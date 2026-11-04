from django.contrib import admin

from .models import Inventory, StockMovement


class ReadOnlyAdmin(admin.ModelAdmin):
    """Stock changes must go through services so every change creates a movement."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Inventory)
class InventoryAdmin(ReadOnlyAdmin):
    list_display = ("variant", "quantity_on_hand", "quantity_reserved", "available", "status")
    list_select_related = ("variant__product",)
    search_fields = ("variant__name", "variant__product__name")


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "variant", "movement_type", "quantity", "reference", "reason")
    list_filter = ("movement_type",)
    list_select_related = ("variant__product",)
    search_fields = ("reference", "reason")