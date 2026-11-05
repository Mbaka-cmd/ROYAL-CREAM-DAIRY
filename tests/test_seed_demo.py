from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.catalogue.models import Product, ProductVariant
from apps.inventory.models import Inventory


class SeedDemoTests(TestCase):
    @override_settings(DEBUG=False)
    def test_refuses_outside_development(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo")
        self.assertEqual(Product.objects.count(), 0)

    @override_settings(DEBUG=True)
    def test_creates_products_with_stock_and_is_repeatable(self):
        call_command("seed_demo")
        self.assertEqual(Product.objects.count(), 4)
        milk = ProductVariant.objects.get(product__slug="fresh-milk", name="1 litre")
        self.assertEqual(milk.price, Decimal("80.00"))
        self.assertEqual(Inventory.objects.get(variant=milk).quantity_on_hand, 20)
        call_command("seed_demo")
        self.assertEqual(Product.objects.count(), 4)
        self.assertEqual(ProductVariant.objects.count(), 6)
        self.assertEqual(Inventory.objects.get(variant=milk).quantity_on_hand, 20)

    @override_settings(DEBUG=True)
    def test_demo_products_appear_in_the_shop(self):
        call_command("seed_demo")
        self.assertContains(self.client.get("/products/"), "Fresh Milk")