from django.contrib import admin, messages

from . import services
from .models import Notification, WebhookEvent


@admin.action(description="Re-queue selected failed notifications")
def requeue_selected(modeladmin, request, queryset):
    if not request.user.has_perm("notifications.change_notification"):
        modeladmin.message_user(request, "You do not have permission to do that.", messages.ERROR)
        return
    count = services.requeue(queryset.values_list("pk", flat=True))
    modeladmin.message_user(request, f"{count} notification(s) re-queued.")


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "order", "recipient_type", "event", "status", "attempts", "last_error")
    list_filter = ("status", "recipient_type", "event")
    list_select_related = ("order",)
    search_fields = ("order__reference", "message_id")
    actions = [requeue_selected]


@admin.register(WebhookEvent)
class WebhookEventAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "message_id", "status", "processed", "error_code")
    list_filter = ("status", "processed")
    search_fields = ("message_id",)