from django.contrib import admin

from .models import DeliveryZone


@admin.register(DeliveryZone)
class DeliveryZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "fee", "min_order", "is_active", "sort_order")
    list_editable = ("fee", "min_order", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name",)
