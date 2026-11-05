from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class DeliveryZone(models.Model):
    """A place we deliver to (for example a town or estate), with its own fee and minimum order.

    While no active zones exist, checkout falls back to a free-text area and the flat DELIVERY_FEE setting.
    Once at least one zone is active, customers must choose a zone and the fee comes from it.
    """

    name = models.CharField(max_length=100, unique=True)
    fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))]
    )
    min_order = models.DecimalField(
        "minimum order",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Smallest order subtotal (KSh) accepted for this area. 0 means no minimum.",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(fee__gte=0), name="deliveryzone_fee_gte_0"),
            models.CheckConstraint(condition=Q(min_order__gte=0), name="deliveryzone_min_order_gte_0"),
        ]

    def __str__(self):
        return self.name
