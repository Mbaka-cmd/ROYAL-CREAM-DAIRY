from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.catalogue.models import Category, Product, ProductVariant
from apps.inventory import services as inventory
from apps.inventory.models import Inventory

NOTE = "DEMO DATA: replace with real details before launch."

# (category, slug, description, [(variant name, price, unit)])
DEMO = [
    ("Fresh Milk", "fresh-milk", "Fresh milk. Price confirmed (KSh 80). " + NOTE, [("1 litre", "80.00", "L")]),
    ("Mala", "mala", "Placeholder prices. " + NOTE, [("500 ml", "60.00", "ml"), ("1 litre", "110.00", "L")]),
    ("Yoghurt", "yoghurt", "Placeholder prices. " + NOTE, [("Small", "50.00", ""), ("Large", "120.00", "")]),
    ("Butter", "butter", "Placeholder price. " + NOTE, [("250 g", "300.00", "g")]),
]


class Command(BaseCommand):
    help = "Add a few demo products with stock so the local shop is not empty (development only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with development settings (DEBUG on). Refusing.")
        for order, (category_name, slug, description, variants) in enumerate(DEMO):
            category, _ = Category.objects.get_or_create(
                slug=slug, defaults={"name": category_name, "sort_order": order}
            )
            product, _ = Product.objects.get_or_create(
                slug=slug, defaults={"category": category, "name": category_name, "description": description}
            )
            for name, price, unit in variants:
                variant, _ = ProductVariant.objects.get_or_create(
                    product=product, name=name, defaults={"price": price, "unit": unit}
                )
                if not Inventory.objects.filter(variant=variant, quantity_on_hand__gt=0).exists():
                    inventory.receive_stock(variant.id, 20, reason="Demo stock")
        self.stdout.write(self.style.SUCCESS("Demo products ready (20 of each in stock)."))