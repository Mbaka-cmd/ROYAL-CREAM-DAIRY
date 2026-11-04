from django.db import models
from django.utils import timezone


class Notification(models.Model):
    """One outbound WhatsApp message to one recipient (the database outbox)."""

    class Recipient(models.TextChoices):
        OWNER = "OWNER", "Owner"
        CUSTOMER = "CUSTOMER", "Customer"

    class Event(models.TextChoices):
        OWNER_NEW_ORDER = "OWNER_NEW_ORDER", "New order (owner)"
        ORDER_RECEIVED = "ORDER_RECEIVED", "Order received"
        ORDER_CONFIRMED = "ORDER_CONFIRMED", "Order confirmed"
        ORDER_OUT_FOR_DELIVERY = "ORDER_OUT_FOR_DELIVERY", "Out for delivery"
        ORDER_COMPLETED = "ORDER_COMPLETED", "Order completed"
        ORDER_CANCELLED = "ORDER_CANCELLED", "Order cancelled"
        DELIVERY_FAILED = "DELIVERY_FAILED", "Delivery failed"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENDING = "SENDING", "Sending"
        SENT = "SENT", "Sent to WhatsApp"
        DELIVERED = "DELIVERED", "Delivered"
        READ = "READ", "Read"
        FAILED = "FAILED", "Failed"
        GAVE_UP = "GAVE_UP", "Gave up (needs review)"
        SKIPPED = "SKIPPED", "Skipped"

    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="notifications")
    recipient_type = models.CharField(max_length=10, choices=Recipient.choices)
    event = models.CharField(max_length=30, choices=Event.choices)
    recipient_phone = models.CharField(max_length=20, blank=True)
    template_name = models.CharField(max_length=64)
    params = models.JSONField(default=list)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    message_id = models.CharField(max_length=128, blank=True, db_index=True)
    last_error = models.CharField(max_length=500, blank=True)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    claimed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    status_updated_at = models.DateTimeField(null=True, blank=True)
    dedupe_key = models.CharField(max_length=80, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="notif_status_due_idx")]

    def __str__(self):
        return f"{self.event} -> {self.recipient_type} ({self.status})"


class WebhookEvent(models.Model):
    """A delivery-status event from Meta. Stored minimally (no phone numbers or message text)."""

    message_id = models.CharField(max_length=128, db_index=True)
    status = models.CharField(max_length=12)
    event_timestamp = models.BigIntegerField(default=0)
    error_code = models.CharField(max_length=20, blank=True)
    error_title = models.CharField(max_length=200, blank=True)
    processed = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["message_id", "status", "event_timestamp"], name="uniq_webhook_event"
            ),
        ]

    def __str__(self):
        return f"{self.status} {self.message_id}"