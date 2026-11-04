from django.db.models import F, IntegerField, Prefetch, Value
from django.db.models.functions import Coalesce

from .models import Product, ProductVariant


def _available():
    return Coalesce(
        F("inventory__quantity_on_hand") - F("inventory__quantity_reserved"),
        Value(0),
        output_field=IntegerField(),
    )


def sellable_variants():
    """Variants a customer may buy, annotated with `available` (0 if no inventory row)."""
    return (
        ProductVariant.objects.filter(
            is_active=True,
            product__is_active=True,
            product__category__is_active=True,
        )
        .select_related("product")
        .annotate(available=_available())
    )


def storefront_products(category_slug=None):
    variants = (
        ProductVariant.objects.filter(is_active=True)
        .annotate(available=_available())
        .order_by("price", "id")
    )
    qs = (
        Product.objects.filter(
            is_active=True,
            category__is_active=True,
            variants__is_active=True,
        )
        .select_related("category")
        .prefetch_related(Prefetch("variants", queryset=variants))
        .distinct()
    )
    if category_slug:
        qs = qs.filter(category__slug=category_slug)
    return qs