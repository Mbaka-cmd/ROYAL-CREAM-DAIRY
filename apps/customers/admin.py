from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "whatsapp_opt_in", "created_at")
    search_fields = ("name", "phone")
    readonly_fields = ("whatsapp_consent_at", "created_at", "updated_at")