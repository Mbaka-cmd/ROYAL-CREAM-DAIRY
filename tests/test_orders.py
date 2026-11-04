import re
import uuid
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from apps.customers.models import Customer
from apps.inventory.models import Inventory, StockMovement
from apps.orders import services
from apps.orders.models import Order, OrderItem, OrderStatusHistory
from tests.helpers import make_variant


@override_settings(DELIVERY_FEE=Decimal("0.00"))
class PlaceOrderTests(TestCase):
    def setUp(self):
        self.milk = make_variant("80.00", 10)
        self.mala = make_variant("50.00", 5)

    def place(self, items, key=None, **over):
        kwargs = dict(
            items=items,
            name="Jane Wanjiku",
            phone="0712345678",
            whatsapp_consent=True,
            delivery_area="Ndagani",
            delivery_address="Near the market",
            idempotency_key=key or uuid.uuid4().hex,
        )
        kwargs.update(over)
        return services.place_order(**kwargs)

    def cart(self, milk=1, mala=0):
        items = [{"variant_id": self.milk.id, "quantity": milk}]
        if mala:
            items.append({"variant_id": self.mala.id, "quantity": mala})
        return items

    def test_happy_path(self):
        order, created = self.place(self.cart(2, 1))
        self.assertTrue(created)
        self.assertRegex(order.reference, r"^RC-\d{4}-\d{5}$")
        self.assertEqual(order.status, Order.Status.NEW)
        self.assertEqual(order.subtotal, Decimal("210.00"))
        self.assertEqual(order.total, Decimal("210.00"))
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(order.customer.phone, "+254712345678")
        self.assertGreaterEqual(len(order.public_token), 20)
        self.assertEqual(Inventory.objects.get(variant=self.milk).quantity_reserved, 2)
        self.assertEqual(Inventory.objects.get(variant=self.mala).quantity_reserved, 1)
        self.assertEqual(OrderStatusHistory.objects.filter(order=order).count(), 1)

    def test_reserve_movement_uses_order_reference(self):
        order, _ = self.place(self.cart(1))
        self.assertTrue(StockMovement.objects.filter(movement_type="RESERVE", reference=order.reference).exists())

    def test_item_prices_are_snapshotted(self):
        order, _ = self.place(self.cart(1))
        self.milk.price = Decimal("100.00")
        self.milk.save()
        self.assertEqual(OrderItem.objects.get(order=order).unit_price, Decimal("80.00"))

    @override_settings(DELIVERY_FEE=Decimal("50.00"))
    def test_delivery_fee_added_server_side(self):
        order, _ = self.place(self.cart(2, 1))
        self.assertEqual(order.delivery_fee, Decimal("50.00"))
        self.assertEqual(order.total, Decimal("260.00"))

    def test_same_idempotency_key_returns_same_order(self):
        first, created1 = self.place(self.cart(2), key="key-1")
        second, created2 = self.place(self.cart(2), key="key-1")
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Inventory.objects.get(variant=self.milk).quantity_reserved, 2)

    def test_insufficient_stock_rolls_back_everything(self):
        with self.assertRaises(services.InsufficientStock):
            self.place(self.cart(11))
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(Inventory.objects.get(variant=self.milk).quantity_reserved, 0)

    def test_failure_on_second_line_releases_first_line(self):
        with self.assertRaises(services.InsufficientStock):
            self.place(self.cart(1, 6))
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Inventory.objects.get(variant=self.milk).quantity_reserved, 0)

    @mock.patch("apps.inventory.services.reserve_stock", side_effect=RuntimeError("boom"))
    def test_exception_midway_rolls_back_order_items_and_customer(self, _):
        with self.assertRaises(RuntimeError):
            self.place(self.cart(1))
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)
        self.assertEqual(Customer.objects.count(), 0)

    def test_unknown_variant_rejected(self):
        with self.assertRaises(services.CheckoutError):
            self.place([{"variant_id": 999999, "quantity": 1}])

    def test_inactive_variant_rejected(self):
        self.milk.is_active = False
        self.milk.save()
        with self.assertRaises(services.CheckoutError):
            self.place(self.cart(1))

    def test_inactive_product_rejected(self):
        self.milk.product.is_active = False
        self.milk.product.save()
        with self.assertRaises(services.CheckoutError):
            self.place(self.cart(1))

    def test_bad_quantities_rejected(self):
        for qty in [0, -2, 51, "abc", None]:
            with self.subTest(qty=qty):
                with self.assertRaises(services.CheckoutError):
                    self.place([{"variant_id": self.milk.id, "quantity": qty}])

    def test_empty_cart_rejected(self):
        with self.assertRaises(services.CheckoutError):
            self.place([])

    def test_invalid_phone_rejected(self):
        with self.assertRaises(services.CheckoutError):
            self.place(self.cart(1), phone="12345")

    def test_missing_or_oversized_key_rejected(self):
        for key in ["", "   ", "x" * 65]:
            with self.subTest(key=key):
                with self.assertRaises(services.CheckoutError):
                    services.place_order(
                        items=self.cart(1), name="Jane", phone="0712345678", whatsapp_consent=True,
                        delivery_area="Chuka", delivery_address="Main road", idempotency_key=key,
                    )

    def test_duplicate_lines_are_merged(self):
        order, _ = self.place([
            {"variant_id": self.milk.id, "quantity": 1},
            {"variant_id": self.milk.id, "quantity": 2},
        ])
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.get().quantity, 3)

    def test_customer_reused_across_orders(self):
        self.place(self.cart(1))
        self.place(self.cart(1))
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(Order.objects.count(), 2)

    def test_consent_recorded_only_when_given(self):
        order, _ = self.place(self.cart(1), whatsapp_consent=True)
        self.assertTrue(order.customer.whatsapp_opt_in)
        order2, _ = self.place(self.cart(1), whatsapp_consent=False)
        order2.customer.refresh_from_db()
        self.assertFalse(order2.customer.whatsapp_opt_in)


@override_settings(DELIVERY_FEE=Decimal("0.00"))
class OrderStatusTests(TestCase):
    def setUp(self):
        self.milk = make_variant("80.00", 10)
        self.order, _ = services.place_order(
            items=[{"variant_id": self.milk.id, "quantity": 2}],
            name="Jane Wanjiku", phone="0712345678", whatsapp_consent=True,
            delivery_area="Chuka", delivery_address="Main road", idempotency_key=uuid.uuid4().hex,
        )

    def inv(self):
        return Inventory.objects.get(variant=self.milk)

    def test_full_flow_deducts_stock_on_completion(self):
        for status in ["CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY"]:
            services.change_status(self.order.pk, status)
            self.assertEqual((self.inv().quantity_on_hand, self.inv().quantity_reserved), (10, 2))
        services.change_status(self.order.pk, "COMPLETED")
        self.assertEqual((self.inv().quantity_on_hand, self.inv().quantity_reserved), (8, 0))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "COMPLETED")
        self.assertEqual(self.order.status_history.count(), 5)

    def test_cancel_releases_exactly_once(self):
        services.change_status(self.order.pk, "CANCELLED", note="Customer changed mind")
        self.assertEqual((self.inv().quantity_on_hand, self.inv().quantity_reserved), (10, 0))
        with self.assertRaises(services.InvalidTransition):
            services.change_status(self.order.pk, "CANCELLED", note="again")
        self.assertEqual(self.inv().quantity_reserved, 0)
        self.assertEqual(StockMovement.objects.filter(movement_type="RELEASE").count(), 1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.cancel_reason, "Customer changed mind")

    def test_cancel_requires_reason(self):
        with self.assertRaises(services.InvalidTransition):
            services.change_status(self.order.pk, "CANCELLED", note="  ")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "NEW")
        self.assertEqual(self.inv().quantity_reserved, 2)

    def test_invalid_transitions_rejected(self):
        for target in ["PREPARING", "OUT_FOR_DELIVERY", "COMPLETED", "DELIVERY_FAILED", "NEW"]:
            with self.subTest(target=target):
                with self.assertRaises(services.InvalidTransition):
                    services.change_status(self.order.pk, target)

    def test_unknown_status_rejected(self):
        with self.assertRaises(services.InvalidTransition):
            services.change_status(self.order.pk, "SHIPPED")

    def test_completed_and_cancelled_are_terminal(self):
        services.change_status(self.order.pk, "CANCELLED", note="test")
        with self.assertRaises(services.InvalidTransition):
            services.change_status(self.order.pk, "CONFIRMED")

    def test_delivery_failed_keeps_reservation_until_cancelled(self):
        for status in ["CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY", "DELIVERY_FAILED"]:
            services.change_status(self.order.pk, status)
        self.assertEqual(self.inv().quantity_reserved, 2)
        services.change_status(self.order.pk, "CANCELLED", note="Customer unreachable")
        self.assertEqual((self.inv().quantity_on_hand, self.inv().quantity_reserved), (10, 0))