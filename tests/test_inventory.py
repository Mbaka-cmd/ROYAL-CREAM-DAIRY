from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.inventory import services
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.selectors import low_stock_items
from tests.helpers import make_variant


class InventoryServiceTests(TestCase):
    def test_receive_increases_on_hand_and_logs(self):
        v = make_variant(on_hand=0)
        row = services.receive_stock(v.id, 10, reason="Opening stock")
        self.assertEqual(row.quantity_on_hand, 10)
        m = StockMovement.objects.get(variant=v)
        self.assertEqual((m.movement_type, m.quantity), ("RECEIVE", 10))

    def test_reserve_reduces_available_not_on_hand(self):
        v = make_variant(on_hand=20)
        services.reserve_stock({v.id: 3}, reference="RC-T-1")
        row = Inventory.objects.get(variant=v)
        self.assertEqual((row.quantity_on_hand, row.quantity_reserved, row.available), (20, 3, 17))
        self.assertTrue(StockMovement.objects.filter(variant=v, movement_type="RESERVE", reference="RC-T-1").exists())

    def test_insufficient_stock_changes_nothing(self):
        v = make_variant(on_hand=2)
        with self.assertRaises(services.InsufficientStock):
            services.reserve_stock({v.id: 3}, reference="RC-T-2")
        self.assertEqual(Inventory.objects.get(variant=v).quantity_reserved, 0)
        self.assertFalse(StockMovement.objects.filter(movement_type="RESERVE").exists())

    def test_multi_variant_reservation_is_all_or_nothing(self):
        a = make_variant(on_hand=5)
        b = make_variant(on_hand=1)
        with self.assertRaises(services.InsufficientStock):
            services.reserve_stock({a.id: 2, b.id: 2}, reference="RC-T-3")
        self.assertEqual(Inventory.objects.get(variant=a).quantity_reserved, 0)
        self.assertEqual(Inventory.objects.get(variant=b).quantity_reserved, 0)

    def test_variant_without_inventory_row_counts_as_zero(self):
        v = make_variant(on_hand=0)
        with self.assertRaises(services.InsufficientStock):
            services.reserve_stock({v.id: 1}, reference="RC-T-4")

    def test_release_restores_availability(self):
        v = make_variant(on_hand=10)
        services.reserve_stock({v.id: 4}, reference="RC-T-5")
        services.release_reservation({v.id: 4}, reference="RC-T-5", reason="cancelled")
        row = Inventory.objects.get(variant=v)
        self.assertEqual((row.quantity_on_hand, row.quantity_reserved), (10, 0))

    def test_cannot_release_more_than_reserved(self):
        v = make_variant(on_hand=10)
        services.reserve_stock({v.id: 1}, reference="RC-T-6")
        with self.assertRaises(services.InventoryError):
            services.release_reservation({v.id: 2}, reference="RC-T-6")

    def test_fulfil_sale_deducts_on_hand_and_reserved(self):
        v = make_variant(on_hand=10)
        services.reserve_stock({v.id: 3}, reference="RC-T-7")
        services.fulfil_sale({v.id: 3}, reference="RC-T-7")
        row = Inventory.objects.get(variant=v)
        self.assertEqual((row.quantity_on_hand, row.quantity_reserved), (7, 0))
        self.assertTrue(StockMovement.objects.filter(variant=v, movement_type="SALE").exists())

    def test_adjustment_requires_reason(self):
        v = make_variant(on_hand=10)
        for reason in ["", "   ", None]:
            with self.subTest(reason=reason):
                with self.assertRaises(services.InventoryError):
                    services.adjust_stock(v.id, 1, reason=reason)

    def test_adjustment_cannot_go_below_reserved(self):
        v = make_variant(on_hand=10)
        services.reserve_stock({v.id: 6}, reference="RC-T-8")
        with self.assertRaises(services.InventoryError):
            services.adjust_stock(v.id, -5, reason="count correction")

    def test_adjustment_up_and_down_is_logged(self):
        v = make_variant(on_hand=10)
        services.adjust_stock(v.id, 5, reason="found extra")
        services.adjust_stock(v.id, -3, reason="spoiled")
        self.assertEqual(Inventory.objects.get(variant=v).quantity_on_hand, 12)
        self.assertEqual(StockMovement.objects.filter(variant=v, movement_type="ADJUST").count(), 2)

    def test_waste_requires_reason_and_reduces_stock(self):
        v = make_variant(on_hand=10)
        with self.assertRaises(services.InventoryError):
            services.record_waste(v.id, 2, reason="")
        services.record_waste(v.id, 2, reason="expired")
        self.assertEqual(Inventory.objects.get(variant=v).quantity_on_hand, 8)

    def test_database_blocks_reserved_above_on_hand(self):
        v = make_variant(on_hand=5)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Inventory.objects.filter(variant=v).update(quantity_reserved=99)

    def test_invalid_quantities_rejected(self):
        v = make_variant(on_hand=5)
        for qty in [0, -1, True, 1.5]:
            with self.subTest(qty=qty):
                with self.assertRaises(services.InventoryError):
                    services.reserve_stock({v.id: qty}, reference="RC-T-9")

    def test_low_stock_selector(self):
        low = make_variant(on_hand=3)
        ok = make_variant(on_hand=50)
        ids = [row.variant_id for row in low_stock_items()]
        self.assertIn(low.id, ids)
        self.assertNotIn(ok.id, ids)