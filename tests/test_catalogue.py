from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from apps.catalogue.models import Category, Product, ProductVariant


class CatalogueModelTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Fresh Milk", slug="fresh-milk")
        self.product = Product.objects.create(category=self.category, name="Fresh Milk", slug="fresh-milk")

    def test_zero_price_rejected_at_db_level(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProductVariant.objects.create(product=self.product, name="1 litre", price=Decimal("0"))

    def test_negative_price_rejected_at_db_level(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProductVariant.objects.create(product=self.product, name="1 litre", price=Decimal("-5"))

    def test_full_clean_rejects_zero_price(self):
        variant = ProductVariant(product=self.product, name="1 litre", price=Decimal("0"))
        with self.assertRaises(ValidationError):
            variant.full_clean()

    def test_duplicate_product_slug_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.create(category=self.category, name="Other", slug="fresh-milk")

    def test_duplicate_variant_name_per_product_rejected(self):
        ProductVariant.objects.create(product=self.product, name="1 litre", price=Decimal("80"))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProductVariant.objects.create(product=self.product, name="1 litre", price=Decimal("85"))

    def test_same_variant_name_allowed_on_different_products(self):
        other = Product.objects.create(category=self.category, name="Mala", slug="mala")
        ProductVariant.objects.create(product=self.product, name="1 litre", price=Decimal("80"))
        ProductVariant.objects.create(product=other, name="1 litre", price=Decimal("120"))
        self.assertEqual(ProductVariant.objects.count(), 2)

    def test_product_with_variants_cannot_be_deleted(self):
        ProductVariant.objects.create(product=self.product, name="1 litre", price=Decimal("80"))
        with self.assertRaises(ProtectedError):
            self.product.delete()

    def test_category_with_products_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.category.delete()

    def test_price_stored_as_exact_decimal(self):
        variant = ProductVariant.objects.create(product=self.product, name="1 litre", price=Decimal("80"))
        variant.refresh_from_db()
        self.assertEqual(variant.price, Decimal("80.00"))
        self.assertIsInstance(variant.price, Decimal)