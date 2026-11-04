import itertools
from decimal import Decimal

from apps.catalogue.models import Category, Product, ProductVariant
from apps.inventory import services as inventory

_counter = itertools.count(1)


def make_variant(price="80.00", on_hand=10, name="1 litre"):
    n = next(_counter)
    category, _ = Category.objects.get_or_create(slug="test-category", defaults={"name": "Test Category"})
    product = Product.objects.create(category=category, name=f"Product {n}", slug=f"product-{n}")
    variant = ProductVariant.objects.create(product=product, name=name, price=Decimal(price))
    if on_hand:
        inventory.receive_stock(variant.id, on_hand, reason="test setup")
    return variant