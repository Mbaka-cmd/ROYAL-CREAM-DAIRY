import json
import uuid
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.delivery.models import DeliveryZone
from apps.orders import services
from apps.orders.cart import price_cart
from apps.orders.models import Order
from tests.helpers import make_variant


@override_settings(DELIVERY_FEE=Decimal("0.00"), CHECKOUT_RATE_LIMIT="1000/m", CART_VALIDATE_RATE_LIMIT="1000/m")
class DeliveryZoneTests(TestCase):
    def setUp(self):
        cache.clear()
        self.milk = make_variant("80.00", 20)
        self.town = DeliveryZone.objects.create(name="Chuka Town", fee=Decimal("50.00"), min_order=Decimal("100.00"), sort_order=1)
        self.near = DeliveryZone.objects.create(name="Nearby Area", fee=Decimal("0.00"), sort_order=2)

    def cart(self, qty=2):
        return [{"variant_id": self.milk.id, "quantity": qty}]

    def place(self, **over):
        kwargs = dict(
            items=self.cart(),
            name="Jane Wanjiku",
            phone="0712345678",
            whatsapp_consent=False,
            delivery_area="",
            delivery_address="Near the market",
            idempotency_key=uuid.uuid4().hex,
            delivery_zone_id=self.town.id,
        )
        kwargs.update(over)
        return services.place_order(**kwargs)

    def test_zone_sets_area_and_fee(self):
        order, _ = self.place()
        self.assertEqual(order.delivery_area, "Chuka Town")
        self.assertEqual(order.delivery_fee, Decimal("50.00"))
        self.assertEqual(order.subtotal, Decimal("160.00"))
        self.assertEqual(order.total, Decimal("210.00"))

    def test_zero_fee_zone_is_free(self):
        order, _ = self.place(delivery_zone_id=self.near.id)
        self.assertEqual(order.delivery_fee, Decimal("0.00"))
        self.assertEqual(order.total, Decimal("160.00"))

    def test_zone_required_once_zones_exist(self):
        for bad in (None, "", "abc", 999999):
            with self.subTest(zone=bad):
                with self.assertRaisesMessage(services.CheckoutError, "choose your delivery area"):
                    self.place(delivery_zone_id=bad)
        self.assertEqual(Order.objects.count(), 0)

    def test_inactive_zone_rejected(self):
        self.near.is_active = False
        self.near.save()
        with self.assertRaisesMessage(services.CheckoutError, "choose your delivery area"):
            self.place(delivery_zone_id=self.near.id)

    def test_client_supplied_area_text_is_ignored_when_zone_chosen(self):
        order, _ = self.place(delivery_area="Somewhere else")
        self.assertEqual(order.delivery_area, "Chuka Town")

    def test_minimum_order_enforced(self):
        with self.assertRaisesMessage(services.CheckoutError, "minimum order for Chuka Town is KSh 100"):
            self.place(items=self.cart(1))  # 80 < 100
        self.assertEqual(Order.objects.count(), 0)

    def test_minimum_order_failure_reserves_no_stock(self):
        try:
            self.place(items=self.cart(1))
        except services.CheckoutError:
            pass
        self.milk.inventory.refresh_from_db()
        self.assertEqual(self.milk.inventory.quantity_reserved, 0)

    def test_without_zones_old_behaviour_remains(self):
        DeliveryZone.objects.all().delete()
        order, _ = self.place(delivery_area="Ndagani", delivery_zone_id=None)
        self.assertEqual(order.delivery_area, "Ndagani")
        self.assertEqual(order.delivery_fee, Decimal("0.00"))

    def test_price_cart_uses_zone_fee(self):
        data = price_cart(self.cart(2), self.town.id)
        self.assertEqual((data["subtotal"], data["delivery_fee"], data["total"]), ("160.00", "50.00", "210.00"))
        self.assertTrue(data["valid"])
        self.assertEqual(data["notice"], "")

    def test_price_cart_flags_minimum_and_ignores_bad_zone(self):
        low = price_cart(self.cart(1), self.town.id)
        self.assertFalse(low["valid"])
        self.assertIn("minimum order", low["notice"])
        for bad in ("abc", 999999, None, ""):
            data = price_cart(self.cart(1), bad)
            self.assertTrue(data["valid"])
            self.assertEqual(data["delivery_fee"], "0.00")


@override_settings(DELIVERY_FEE=Decimal("0.00"), CHECKOUT_RATE_LIMIT="1000/m", CART_VALIDATE_RATE_LIMIT="1000/m")
class DeliveryZoneViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.milk = make_variant("80.00", 20)
        self.town = DeliveryZone.objects.create(name="Chuka Town", fee=Decimal("50.00"))

    def data(self, **over):
        data = {
            "cart": json.dumps([{"variant_id": self.milk.id, "quantity": 2}]),
            "idempotency_key": uuid.uuid4().hex,
            "name": "Jane Wanjiku",
            "phone": "0712345678",
            "delivery_zone": str(self.town.id),
            "delivery_address": "Near the market",
        }
        data.update(over)
        return data

    def test_checkout_page_shows_zone_dropdown(self):
        response = self.client.get("/checkout/")
        self.assertContains(response, 'name="delivery_zone"')
        self.assertContains(response, "Chuka Town (delivery KSh 50)")
        self.assertNotContains(response, 'name="delivery_area"')

    def test_checkout_page_without_zones_keeps_text_field(self):
        DeliveryZone.objects.all().delete()
        response = self.client.get("/checkout/")
        self.assertContains(response, 'name="delivery_area"')
        self.assertNotContains(response, 'name="delivery_zone"')

    def test_order_places_with_zone_and_confirmation_shows_it(self):
        response = self.client.post("/checkout/", self.data())
        order = Order.objects.get()
        self.assertRedirects(response, f"/order/{order.public_token}/")
        self.assertEqual((order.delivery_area, order.delivery_fee, order.total), ("Chuka Town", Decimal("50.00"), Decimal("210.00")))
        page = self.client.get(f"/order/{order.public_token}/")
        self.assertContains(page, "Chuka Town")
        self.assertContains(page, "KSh 50")

    def test_missing_zone_is_rejected_and_form_kept(self):
        response = self.client.post("/checkout/", self.data(delivery_zone=""))
        self.assertContains(response, "choose your delivery area", status_code=400)
        self.assertContains(response, "Jane Wanjiku", status_code=400)
        self.assertEqual(Order.objects.count(), 0)

    def test_cart_validate_returns_zone_fee(self):
        payload = {"items": [{"variant_id": self.milk.id, "quantity": 2}], "zone": self.town.id}
        response = self.client.post("/api/cart/validate/", json.dumps(payload), content_type="application/json")
        body = response.json()
        self.assertEqual((body["delivery_fee"], body["total"]), ("50.00", "210.00"))
