from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    """A product family (e.g. Fresh Milk). Sellable items are ProductVariants."""

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="products/", blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["is_active", "category"], name="product_active_category_idx")]

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    """The actual sellable item, e.g. Fresh Milk / 1 litre / KSh 80."""

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="variants")
    name = models.CharField(max_length=100)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    unit = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["product_id", "price"]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gt=0), name="variant_price_gt_zero"),
            models.UniqueConstraint(fields=["product", "name"], name="uniq_variant_name_per_product"),
        ]

    def __str__(self):
        return f"{self.product.name} {self.name}"