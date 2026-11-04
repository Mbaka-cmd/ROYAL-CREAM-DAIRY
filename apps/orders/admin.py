from django.contrib import admin

from .models import Order, OrderItem, OrderStatusHistory


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OrderItemInline(ReadOnlyInline):
    model = OrderItem


class StatusHistoryInline(ReadOnlyInline):
    model = OrderStatusHistory


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """View only. Status changes go through apps.orders.services.change_status."""

    list_display = ("reference", "customer", "status", "total", "created_at")
    list_filter = ("status",)
    list_select_related = ("customer",)
    search_fields = ("reference", "customer__name", "customer__phone")
    inlines = [OrderItemInline, StatusHistoryInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False