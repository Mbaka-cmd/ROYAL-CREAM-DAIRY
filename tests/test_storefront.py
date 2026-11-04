import json
import uuid
from decimal import Decimal

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from apps.catalogue.models import Category
from apps.inventory.models import Inventory
from apps.orders import services
from apps.orders.models import Order
from tests.helpers import make_variant


def named(name, price="80.00", on_hand=10):
    variant = make_variant(price, on_hand)
    variant.product.name = name
    variant.product.save()
    return variant


class StorefrontPageTests(TestCase):
    def test_home_lists_active_products_only(self):
        named("Alpha Milk")
        hidden = named("Beta Mala")
        hidden.product.is_active = False
        hidden.product.save()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha Milk")
        self.assertNotContains(response, "Beta Mala")

    def test_home_hides_products_in_inactive_category(self):
        v = named("Alpha Milk")
        v.product.category.is_active = False
        v.product.category.save()
        self.assertNotContains(self.client.get("/"), "Alpha Milk")

    def test_home_with_no_products(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "coming soon")

    def test_inactive_variant_not_listed(self):
        v = named("Alpha Milk")
        other = make_variant("55.00", 5, name="500 ml")
        other.product = v.product
        other.save()
        other.is_active = False
        other.save()
        response = self.client.get("/products/")
        self.assertNotContains(response, "500 ml")

    def test_product_list_shows_out_of_stock_without_inventory(self):
        named("Gamma Butter", on_hand=0)
        response = self.client.get("/products/")
        self.assertContains(response, "Gamma Butter")
        self.assertContains(response, "Out of stock")

    def test_product_list_shows_add_button_when_in_stock(self):
        v = named("Alpha Milk", on_hand=4)
        response = self.client.get("/products/")
        self.assertContains(response, f'data-variant="{v.id}"')
        self.assertContains(response, 'data-max="4"')

    def test_reserved_stock_is_not_offered(self):
        from apps.inventory import services as inv

        v = named("Alpha Milk", on_hand=3)
        inv.reserve_stock({v.id: 3}, reference="RC-T-X")
        response = self.client.get("/products/")
        self.assertContains(response, "Out of stock")
        self.assertNotContains(response, f'data-variant="{v.id}"')

    def test_product_list_paginates(self):
        for _ in range(13):
            make_variant("80.00", 5)
        response = self.client.get("/products/")
        self.assertEqual(response.context["page"].paginator.num_pages, 2)
        self.assertEqual(len(response.context["page"].object_list), 12)
        page2 = self.client.get("/products/?page=2")
        self.assertEqual(len(page2.context["page"].object_list), 1)

    def test_bad_page_number_does_not_crash(self):
        make_variant("80.00", 5)
        self.assertEqual(self.client.get("/products/?page=abc").status_code, 200)
        self.assertEqual(self.client.get("/products/?page=999").status_code, 200)

    def test_category_filter(self):
        a = named("Delta Yoghurt")
        named("Epsilon Mala")
        cat = Category.objects.create(name="Yoghurt", slug="yoghurt")
        a.product.category = cat
        a.product.save()
        response = self.client.get("/products/?category=yoghurt")
        self.assertContains(response, "Delta Yoghurt")
        self.assertNotContains(response, "Epsilon Mala")

    def test_product_detail(self):
        v = named("Alpha Milk")
        response = self.client.get(f"/products/{v.product.slug}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha Milk")

    def test_inactive_product_detail_is_404(self):
        v = named("Alpha Milk")
        v.product.is_active = False
        v.product.save()
        self.assertEqual(self.client.get(f"/products/{v.product.slug}/").status_code, 404)

    def test_unknown_product_is_404(self):
        self.assertEqual(self.client.get("/products/nope/").status_code, 404)


@override_settings(DELIVERY_FEE=Decimal("0.00"), CART_VALIDATE_RATE_LIMIT="1000/m")
class CartValidateTests(TestCase):
    url = "/api/cart/validate/"

    def setUp(self):
        cache.clear()

    def post(self, payload=None, raw=None, client=None):
        body = raw if raw is not None else json.dumps(payload)
        return (client or self.client).post(self.url, data=body, content_type="application/json")

    def test_prices_come_from_database_not_client(self):
        v = named("Zeta Milk", "80.00", 10)
        data = self.post({"items": [{"variant_id": v.id, "quantity": 2, "price": "1.00", "unit_price": "1"}]}).json()
        line = data["lines"][0]
        self.assertEqual(line["unit_price"], "80.00")
        self.assertEqual(line["line_total"], "160.00")
        self.assertEqual((data["subtotal"], data["total"], data["valid"]), ("160.00", "160.00", True))

    @override_settings(DELIVERY_FEE=Decimal("50.00"))
    def test_delivery_fee_added(self):
        v = named("Zeta Milk", "80.00", 10)
        data = self.post({"items": [{"variant_id": v.id, "quantity": 2}]}).json()
        self.assertEqual((data["subtotal"], data["delivery_fee"], data["total"]), ("160.00", "50.00", "210.00"))

    def test_over_stock_is_flagged(self):
        v = named("Zeta Milk", "80.00", 3)
        data = self.post({"items": [{"variant_id": v.id, "quantity": 5}]}).json()
        self.assertFalse(data["valid"])
        self.assertFalse(data["lines"][0]["ok"])
        self.assertEqual(data["lines"][0]["message"], "Only 3 available")

    def test_out_of_stock_is_flagged(self):
        v = named("Zeta Milk", "80.00", 0)
        data = self.post({"items": [{"variant_id": v.id, "quantity": 1}]}).json()
        self.assertFalse(data["valid"])
        self.assertEqual(data["lines"][0]["message"], "Out of stock")

    def test_unknown_and_inactive_variants_are_listed_unavailable(self):
        v = named("Zeta Milk", "80.00", 10)
        v.is_active = False
        v.save()
        data = self.post({"items": [{"variant_id": v.id, "quantity": 1}, {"variant_id": 999999, "quantity": 1}]}).json()
        self.assertEqual(sorted(data["unavailable"]), sorted([v.id, 999999]))
        self.assertFalse(data["valid"])
        self.assertEqual(data["lines"], [])

    def test_junk_items_are_ignored(self):
        v = named("Zeta Milk", "80.00", 10)
        data = self.post({"items": [{"variant_id": "x", "quantity": 1}, {"variant_id": v.id, "quantity": -3}, {}, 5]}).json()
        self.assertEqual(data["lines"], [])
        self.assertFalse(data["valid"])

    def test_duplicate_lines_merge(self):
        v = named("Zeta Milk", "80.00", 10)
        data = self.post({"items": [{"variant_id": v.id, "quantity": 1}, {"variant_id": v.id, "quantity": 2}]}).json()
        self.assertEqual(len(data["lines"]), 1)
        self.assertEqual(data["lines"][0]["quantity"], 3)

    def test_csrf_is_enforced(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.post({"items": []}, client=client).status_code, 403)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_invalid_json_rejected(self):
        self.assertEqual(self.post(raw="{nope").status_code, 400)

    def test_items_must_be_a_list(self):
        self.assertEqual(self.post({"items": "x"}).status_code, 400)
        self.assertEqual(self.post([1, 2]).status_code, 400)

    def test_oversized_body_rejected(self):
        self.assertEqual(self.post(raw="a" * 20_001).status_code, 413)

    def test_rate_limited(self):
        with self.settings(CART_VALIDATE_RATE_LIMIT="2/m"):
            cache.clear()
            codes = [self.post({"items": []}).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])


@override_settings(DELIVERY_FEE=Decimal("0.00"), CHECKOUT_RATE_LIMIT="1000/m")
class CheckoutViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.milk = named("Eta Milk", "80.00", 10)

    def data(self, qty=2, **over):
        data = {
            "cart": json.dumps([{"variant_id": self.milk.id, "quantity": qty}]),
            "idempotency_key": uuid.uuid4().hex,
            "name": "Jane Wanjiku",
            "phone": "0712345678",
            "delivery_area": "Ndagani",
            "delivery_address": "Near the market",
            "delivery_instructions": "",
            "whatsapp_consent": "on",
        }
        data.update(over)
        return data

    def test_get_renders_form_with_csrf(self):
        response = self.client.get("/checkout/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "Pay on delivery")

    def test_valid_order_redirects_to_confirmation(self):
        response = self.client.post("/checkout/", self.data(2, total="1", subtotal="1"))
        order = Order.objects.get()
        self.assertRedirects(response, f"/order/{order.public_token}/")
        self.assertEqual(order.total, Decimal("160.00"))
        self.assertEqual(Inventory.objects.get(variant=self.milk).quantity_reserved, 2)
        self.assertTrue(order.customer.whatsapp_opt_in)

    def test_double_submit_with_same_key_creates_one_order(self):
        data = self.data(2)
        first = self.client.post("/checkout/", data)
        second = self.client.post("/checkout/", data)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(first["Location"], second["Location"])
        self.assertEqual(Inventory.objects.get(variant=self.milk).quantity_reserved, 2)

    def test_consent_unchecked_is_recorded_as_no_consent(self):
        data = self.data(1)
        data.pop("whatsapp_consent")
        self.client.post("/checkout/", data)
        self.assertFalse(Order.objects.get().customer.whatsapp_opt_in)

    def test_invalid_phone_rejected_and_form_preserved(self):
        response = self.client.post("/checkout/", self.data(1, phone="12345"))
        self.assertContains(response, "valid Kenyan phone", status_code=400)
        self.assertContains(response, "Jane Wanjiku", status_code=400)
        self.assertEqual(Order.objects.count(), 0)

    def test_insufficient_stock_returns_409_and_creates_nothing(self):
        response = self.client.post("/checkout/", self.data(11))
        self.assertContains(response, "only 10", status_code=409)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Inventory.objects.get(variant=self.milk).quantity_reserved, 0)

    def test_sold_out_message(self):
        from apps.inventory import services as inv

        inv.reserve_stock({self.milk.id: 10}, reference="RC-T-Y")
        response = self.client.post("/checkout/", self.data(1))
        self.assertContains(response, "just sold out", status_code=409)

    def test_bad_cart_payloads_rejected(self):
        for cart in ["not json", '{"a": 1}', "[]"]:
            with self.subTest(cart=cart):
                response = self.client.post("/checkout/", self.data(1, cart=cart))
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_missing_key_rejected(self):
        response = self.client.post("/checkout/", self.data(1, idempotency_key=""))
        self.assertContains(response, "reload", status_code=400)
        self.assertEqual(Order.objects.count(), 0)

    def test_honeypot_rejected(self):
        response = self.client.post("/checkout/", self.data(1, website="http://spam.example"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_csrf_enforced_on_checkout(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post("/checkout/", self.data(1)).status_code, 403)

    def test_rate_limited(self):
        with self.settings(CHECKOUT_RATE_LIMIT="2/m"):
            cache.clear()
            codes = [self.client.post("/checkout/", self.data(1, phone="bad")).status_code for _ in range(3)]
        self.assertEqual(codes, [400, 400, 429])
        self.assertEqual(Order.objects.count(), 0)

    def test_get_is_not_rate_limited(self):
        with self.settings(CHECKOUT_RATE_LIMIT="1/m"):
            cache.clear()
            codes = [self.client.get("/checkout/").status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 200])


@override_settings(DELIVERY_FEE=Decimal("0.00"))
class ConfirmationTests(TestCase):
    def setUp(self):
        self.milk = named("Theta Milk", "80.00", 10)
        self.order, _ = services.place_order(
            items=[{"variant_id": self.milk.id, "quantity": 2}],
            name="Jane Wanjiku", phone="0712345678", whatsapp_consent=True,
            delivery_area="Ndagani", delivery_address="Near the market",
            idempotency_key=uuid.uuid4().hex,
        )

    def test_confirmation_page(self):
        response = self.client.get(f"/order/{self.order.public_token}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.reference)
        self.assertContains(response, "Theta Milk")
        self.assertContains(response, "Pay on delivery")
        self.assertContains(response, "noindex")
        self.assertContains(response, 'data-clear-cart="1"')
        self.assertIn("no-store", response["Cache-Control"])

    def test_page_does_not_expose_phone(self):
        response = self.client.get(f"/order/{self.order.public_token}/")
        self.assertNotContains(response, "712345678")

    def test_guessable_identifiers_do_not_work(self):
        for ident in ["nope", str(self.order.pk), self.order.reference]:
            with self.subTest(ident=ident):
                self.assertEqual(self.client.get(f"/order/{ident}/").status_code, 404)


@override_settings(DELIVERY_FEE=Decimal("0.00"))
class SellabilityTests(TestCase):
    def test_inactive_category_blocks_order(self):
        v = named("Iota Milk", "80.00", 10)
        v.product.category.is_active = False
        v.product.category.save()
        with self.assertRaises(services.CheckoutError):
            services.place_order(
                items=[{"variant_id": v.id, "quantity": 1}],
                name="Jane Wanjiku", phone="0712345678", whatsapp_consent=False,
                delivery_area="Chuka", delivery_address="Main road",
                idempotency_key=uuid.uuid4().hex,
            )