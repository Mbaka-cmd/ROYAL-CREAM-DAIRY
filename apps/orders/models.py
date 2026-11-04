import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q


def make_public_token():
    return secrets.token_urlsafe(24)


class Order(models.Model):
    class Status(models.TextChoices):
        NEW = "NEW", "New"
        CONFIRMED = "CONFIRMED", "Confirmed"
        PREPARING = "PREPARING", "Preparing"
        OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", "Out for delivery"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"
        DELIVERY_FAILED = "DELIVERY_FAILED", "Delivery failed"

    class PaymentMethod(models.TextChoices):
        POD = "POD", "Pay on delivery"

    reference = models.CharField(max_length=40, unique=True)
    public_token = models.CharField(max_length=48, unique=True, default=make_public_token)
    idempotency_key = models.CharField(max_length=64, unique=True)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="orders")
    delivery_area = models.CharField(max_length=100)
    delivery_address = models.CharField(max_length=255)
    delivery_instructions = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.POD)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    cancel_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(subtotal__gte=0), name="order_subtotal_gte_0"),
            models.CheckConstraint(condition=Q(delivery_fee__gte=0), name="order_delivery_fee_gte_0"),
            models.CheckConstraint(condition=Q(total__gte=0), name="order_total_gte_0"),
        ]

    def __str__(self):
        return self.reference


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey("catalogue.ProductVariant", on_delete=models.PROTECT, related_name="order_items")
    product_name = models.CharField(max_length=150)
    variant_name = models.CharField(max_length=100)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="orderitem_quantity_gt_0"),
            models.CheckConstraint(condition=Q(unit_price__gt=0), name="orderitem_unit_price_gt_0"),
            models.UniqueConstraint(fields=["order", "variant"], name="uniq_variant_per_order"),
        ]

    def __str__(self):
        return f"{self.product_name} {self.variant_name} x {self.quantity}"


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_history")
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20)
    note = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "order status history"

    def __str__(self):
        return f"{self.order.reference}: {self.old_status or '-'} -> {self.new_status}"