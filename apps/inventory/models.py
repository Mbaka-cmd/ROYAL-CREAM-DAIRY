from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Inventory(models.Model):
    variant = models.OneToOneField(
        "catalogue.ProductVariant", on_delete=models.PROTECT, related_name="inventory"
    )
    quantity_on_hand = models.PositiveIntegerField(default=0)
    quantity_reserved = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "inventory"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_reserved__lte=F("quantity_on_hand")),
                name="inventory_reserved_lte_on_hand",
            ),
        ]

    @property
    def available(self):
        return self.quantity_on_hand - self.quantity_reserved

    @property
    def status(self):
        if self.available <= 0:
            return "Out of stock"
        if self.available <= self.low_stock_threshold:
            return "Low stock"
        return "In stock"

    def __str__(self):
        return f"{self.variant} stock"


class StockMovement(models.Model):
    class Type(models.TextChoices):
        RECEIVE = "RECEIVE", "Received"
        ADJUST = "ADJUST", "Adjustment"
        RESERVE = "RESERVE", "Reserved"
        RELEASE = "RELEASE", "Reservation released"
        SALE = "SALE", "Sale"
        WASTE = "WASTE", "Waste"

    variant = models.ForeignKey(
        "catalogue.ProductVariant", on_delete=models.PROTECT, related_name="stock_movements"
    )
    movement_type = models.CharField(max_length=10, choices=Type.choices)
    quantity = models.IntegerField()
    reference = models.CharField(max_length=40, blank=True, db_index=True)
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["variant", "created_at"], name="stockmove_variant_date_idx")]
        constraints = [
            models.CheckConstraint(condition=~Q(quantity=0), name="stock_movement_qty_nonzero"),
        ]

    def __str__(self):
        return f"{self.movement_type} {self.quantity} x variant {self.variant_id}"