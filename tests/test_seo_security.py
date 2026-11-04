import importlib
import json
import os
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.catalogue.models import Category, ProductVariant
from apps.customers import privacy
from apps.customers.models import Customer
from apps.notifications.models import Notification
from apps.orders import services as order_services
from apps.orders.models import Order
from config import checks
from tests.helpers import make_variant

SEO = dict(
    SITE_URL="https://shop.test",
    GA_MEASUREMENT_ID="",
    PUBLIC_WHATSAPP_NUMBER="",
    SOCIAL_FACEBOOK_URL="",
    SOCIAL_TIKTOK_URL="",
    GOOGLE_SITE_VERIFICATION="",
    PRIVACY_CONTACT_EMAIL="",
    DEFAULT_OG_IMAGE="",
    DELIVERY_FEE=Decimal("0.00"),
    DEBUG=False,
)
GA = "G-TEST1234"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def named(name, price="80.00", on_hand=10):
    variant = make_variant(price, on_hand)
    variant.product.name = name
    variant.product.save()
    return variant


def placed(consent=True, milk=None, qty=2):
    milk = milk or make_variant("80.00", 50)
    order, _ = order_services.place_order(
        items=[{"variant_id": milk.id, "quantity": qty}],
        name="Jane Wanjiku", phone="0712345678", whatsapp_consent=consent,
        delivery_area="Ndagani", delivery_address="Near the market", delivery_instructions="Blue gate",
        idempotency_key=uuid.uuid4().hex,
    )
    return order


def complete(order):
    for status in ["CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY", "COMPLETED"]:
        order_services.change_status(order.pk, status)


def ld_blocks(html):
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


@override_settings(**SEO)
class RobotsSitemapTests(TestCase):
    def test_robots(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/plain"))
        body = response.content.decode()
        for path in ["/owner/", "/django-admin/", "/checkout/", "/order/", "/api/", "/webhooks/"]:
            self.assertIn(f"Disallow: {path}", body)
        self.assertIn("Sitemap: https://shop.test/sitemap.xml", body)

    def test_robots_is_read_only(self):
        self.assertEqual(self.client.post("/robots.txt").status_code, 405)

    def test_sitemap_lists_public_pages_and_active_products(self):
        active = named("Alpha Milk")
        hidden = named("Beta Mala")
        hidden.product.is_active = False
        hidden.product.save()
        gone = named("Gamma Butter")
        gone.product.category = Category.objects.create(name="Hidden", slug="hidden", is_active=False)
        gone.product.save()
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"].split(";")[0], "application/xml")
        root = ET.fromstring(response.content)
        locs = [e.text for e in root.findall("s:url/s:loc", NS)]
        self.assertIn("https://shop.test/", locs)
        self.assertIn("https://shop.test/products/", locs)
        self.assertIn("https://shop.test/privacy/", locs)
        self.assertIn(f"https://shop.test/products/{active.product.slug}/", locs)
        self.assertNotIn(f"https://shop.test/products/{hidden.product.slug}/", locs)
        self.assertNotIn(f"https://shop.test/products/{gone.product.slug}/", locs)
        self.assertIsNotNone(root.find("s:url/s:lastmod", NS))

    @override_settings(SITE_URL="")
    def test_sitemap_falls_back_to_request_host(self):
        root = ET.fromstring(self.client.get("/sitemap.xml").content)
        locs = [e.text for e in root.findall("s:url/s:loc", NS)]
        self.assertTrue(all(loc.startswith("http://testserver/") for loc in locs))


@override_settings(**SEO)
class MetaTagTests(TestCase):
    def test_home_meta(self):
        response = self.client.get("/")
        self.assertContains(response, '<link rel="canonical" href="https://shop.test/">')
        self.assertContains(response, '<meta property="og:title" content="Royal Cream Dairy | Pure Goodness, Every Day.">')
        self.assertContains(response, 'property="og:description" content="Fresh dairy products delivered around Chuka."')
        self.assertContains(response, '<meta property="og:url" content="https://shop.test/">')
        self.assertContains(response, '<meta name="twitter:card" content="summary">')
        self.assertNotContains(response, "og:image")
        self.assertContains(response, "Royal Cream Dairy | Fresh Milk, Mala &amp; Yoghurt in Chuka")

    @override_settings(DEFAULT_OG_IMAGE="images/og.png")
    def test_default_og_image(self):
        response = self.client.get("/")
        self.assertContains(response, 'property="og:image" content="https://shop.test/static/images/og.png"')
        self.assertContains(response, 'content="summary_large_image"')

    def test_product_list_canonicals(self):
        for _ in range(13):
            make_variant("80.00", 5)
        self.assertContains(self.client.get("/products/"), 'rel="canonical" href="https://shop.test/products/"')
        self.assertContains(self.client.get("/products/?page=2"), 'rel="canonical" href="https://shop.test/products/?page=2"')
        self.assertContains(self.client.get("/products/?category=zzz"), 'href="https://shop.test/products/?category=zzz"')

    def test_category_page_title(self):
        v = named("Delta Yoghurt")
        cat = Category.objects.create(name="Yoghurt", slug="yoghurt")
        v.product.category = cat
        v.product.save()
        response = self.client.get("/products/?category=yoghurt")
        self.assertContains(response, "<title>Yoghurt | Products | Royal Cream Dairy</title>")

    def test_product_detail_meta(self):
        v = named("Alpha Milk")
        response = self.client.get(f"/products/{v.product.slug}/")
        self.assertContains(response, f'rel="canonical" href="https://shop.test/products/{v.product.slug}/"')
        self.assertContains(response, "<title>Alpha Milk | Royal Cream Dairy</title>")
        self.assertContains(response, 'property="og:title" content="Alpha Milk | Royal Cream Dairy"')
        self.assertContains(response, "Order Alpha Milk from Royal Cream Dairy")

    def test_product_description_and_image_are_used(self):
        v = named("Alpha Milk")
        v.product.description = "Creamy <b>fresh</b> milk"
        v.product.image = "products/x.png"
        v.product.save()
        response = self.client.get(f"/products/{v.product.slug}/")
        self.assertContains(response, 'name="description" content="Creamy fresh milk"')
        self.assertContains(response, 'property="og:image" content="https://shop.test/media/products/x.png"')

    @override_settings(GOOGLE_SITE_VERIFICATION="abc123token")
    def test_search_console_verification(self):
        self.assertContains(self.client.get("/"), '<meta name="google-site-verification" content="abc123token">')

    def test_no_verification_meta_by_default(self):
        self.assertNotContains(self.client.get("/"), "google-site-verification")

    def test_private_pages_are_noindex(self):
        self.assertContains(self.client.get("/checkout/"), "noindex")
        self.assertContains(self.client.get("/owner/login/"), "noindex")

    def test_privacy_page_is_indexable(self):
        self.assertNotContains(self.client.get("/privacy/"), "noindex")

    def test_favicon_and_skip_link(self):
        response = self.client.get("/")
        self.assertContains(response, "icons/favicon.svg")
        self.assertContains(response, 'href="#main"')


@override_settings(**SEO)
class StructuredDataTests(TestCase):
    def test_home_has_organization_and_website_only(self):
        html = self.client.get("/").content.decode()
        graph = ld_blocks(html)[0]["@graph"]
        types = {item["@type"] for item in graph}
        self.assertEqual(types, {"Organization", "WebSite"})
        org = next(i for i in graph if i["@type"] == "Organization")
        self.assertEqual(org["name"], "Royal Cream Dairy")
        self.assertNotIn("sameAs", org)
        self.assertNotIn("LocalBusiness", html)
        self.assertNotIn("aggregateRating", html)

    @override_settings(SOCIAL_FACEBOOK_URL="https://facebook.com/royalcream", SOCIAL_TIKTOK_URL="javascript:alert(1)")
    def test_same_as_only_accepts_https_urls(self):
        org = ld_blocks(self.client.get("/").content.decode())[0]["@graph"][0]
        self.assertEqual(org["sameAs"], ["https://facebook.com/royalcream"])

    @override_settings(SOCIAL_FACEBOOK_URL="https://facebook.com/royalcream", SOCIAL_TIKTOK_URL="http://insecure.example")
    def test_footer_links_only_for_https(self):
        response = self.client.get("/")
        self.assertContains(response, 'href="https://facebook.com/royalcream"')
        self.assertNotContains(response, "insecure.example")

    def test_product_offers_have_real_prices_and_availability(self):
        v = named("Alpha Milk", "80.00", 10)
        ProductVariant.objects.create(product=v.product, name="500 ml", price=Decimal("45.00"))
        data = ld_blocks(self.client.get(f"/products/{v.product.slug}/").content.decode())[0]
        self.assertEqual(data["@type"], "Product")
        self.assertEqual(data["name"], "Alpha Milk")
        offers = {o["name"]: o for o in data["offers"]}
        self.assertEqual(offers["1 litre"]["price"], "80.00")
        self.assertEqual(offers["1 litre"]["priceCurrency"], "KES")
        self.assertEqual(offers["1 litre"]["availability"], "https://schema.org/InStock")
        self.assertEqual(offers["500 ml"]["price"], "45.00")
        self.assertEqual(offers["500 ml"]["availability"], "https://schema.org/OutOfStock")
        for forbidden in ("aggregateRating", "review", "brand", "gtin"):
            self.assertNotIn(forbidden, data)

    def test_json_ld_cannot_break_out_of_the_script_tag(self):
        v = named("Bad</script><script>alert(1)</script>")
        v.product.description = "x</script><script>alert(2)</script>"
        v.product.save()
        response = self.client.get(f"/products/{v.product.slug}/")
        html = response.content.decode()
        self.assertNotIn("<script>alert", html)
        data = ld_blocks(html)[0]
        self.assertEqual(data["name"], "Bad</script><script>alert(1)</script>")


@override_settings(**SEO)
class SecurityHeaderTests(TestCase):
    def header(self, path="/"):
        return self.client.get(path)["Content-Security-Policy"]

    def policy(self, path="/"):
        return dict((part.split(" ", 1) + [""])[:2] for part in self.header(path).split("; "))

    def test_strict_policy_on_public_pages(self):
        header = self.header("/")
        policy = self.policy("/")
        self.assertEqual(policy["default-src"], "'self'")
        self.assertEqual(policy["script-src"], "'self'")
        self.assertEqual(policy["style-src"], "'self'")
        self.assertEqual(policy["frame-ancestors"], "'none'")
        self.assertEqual(policy["object-src"], "'none'")
        self.assertEqual(policy["base-uri"], "'self'")
        self.assertEqual(policy["form-action"], "'self'")
        self.assertNotIn("unsafe-inline", header)
        self.assertNotIn("unsafe-eval", header)
        self.assertNotIn("googletagmanager", header)

    def test_strict_policy_on_dashboard_and_errors(self):
        self.assertNotIn("unsafe-inline", self.header("/owner/login/"))
        response = self.client.get("/definitely-missing/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])

    def test_admin_alone_gets_the_relaxed_policy(self):
        policy = self.policy("/django-admin/login/")
        self.assertIn("'unsafe-inline'", policy["script-src"])
        self.assertIn("'unsafe-inline'", policy["style-src"])
        self.assertEqual(policy["frame-ancestors"], "'none'")

    @override_settings(GA_MEASUREMENT_ID=GA)
    def test_google_hosts_are_allowed_only_when_analytics_is_configured(self):
        policy = self.policy("/")
        self.assertEqual(policy["script-src"], "'self' https://*.googletagmanager.com")
        self.assertIn("https://*.google-analytics.com", policy["connect-src"])
        self.assertIn("https://*.analytics.google.com", policy["connect-src"])
        self.assertIn("https://*.google-analytics.com", policy["img-src"])
        self.assertNotIn("unsafe-inline", self.header("/"))

    @override_settings(GA_MEASUREMENT_ID="not-an-id")
    def test_invalid_analytics_id_opens_nothing(self):
        self.assertNotIn("google", self.header("/"))

    def test_upgrade_insecure_requests_only_outside_debug(self):
        self.assertIn("upgrade-insecure-requests", self.header("/"))
        with self.settings(DEBUG=True):
            self.assertNotIn("upgrade-insecure-requests", self.header("/"))

    def test_permissions_policy(self):
        policy = self.client.get("/")["Permissions-Policy"]
        for feature in ("camera=()", "microphone=()", "geolocation=()", "payment=()"):
            self.assertIn(feature, policy)


class ProductionSettingsTests(TestCase):
    KEYS = ["HSTS_SECONDS", "HSTS_INCLUDE_SUBDOMAINS", "BEHIND_HTTPS_PROXY"]

    def load_production(self, **env):
        from config.settings import base

        if not base.SECRET_KEY:
            self.skipTest("SECRET_KEY is not set in this environment")
        clean = {k: v for k, v in os.environ.items() if k not in self.KEYS}
        clean.update(env)
        with mock.patch.dict(os.environ, clean, clear=True):
            module = importlib.import_module("config.settings.production")
            return importlib.reload(module)

    def test_secure_defaults(self):
        prod = self.load_production()
        self.assertIs(prod.DEBUG, False)
        self.assertIs(prod.SECURE_SSL_REDIRECT, True)
        self.assertIs(prod.SESSION_COOKIE_SECURE, True)
        self.assertIs(prod.CSRF_COOKIE_SECURE, True)
        self.assertIs(prod.SESSION_COOKIE_HTTPONLY, True)
        self.assertEqual(prod.X_FRAME_OPTIONS, "DENY")
        self.assertIs(prod.SECURE_CONTENT_TYPE_NOSNIFF, True)
        self.assertEqual(prod.SECURE_HSTS_SECONDS, 0)
        self.assertIs(prod.SECURE_HSTS_PRELOAD, False)
        self.assertFalse(hasattr(prod, "SECURE_PROXY_SSL_HEADER"))

    def test_switches_from_environment(self):
        prod = self.load_production(HSTS_SECONDS="3600", HSTS_INCLUDE_SUBDOMAINS="true", BEHIND_HTTPS_PROXY="true")
        self.assertEqual(prod.SECURE_HSTS_SECONDS, 3600)
        self.assertIs(prod.SECURE_HSTS_INCLUDE_SUBDOMAINS, True)
        self.assertIs(prod.SECURE_HSTS_PRELOAD, False)
        self.assertEqual(prod.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https"))
        self.load_production()  # restore defaults


@override_settings(**SEO)
class AnalyticsTests(TestCase):
    def test_disabled_without_id(self):
        response = self.client.get("/")
        self.assertContains(response, 'data-ga-id=""')
        self.assertContains(response, "js/analytics.js")
        self.assertNotContains(response, "googletagmanager")

    @override_settings(GA_MEASUREMENT_ID=GA)
    def test_enabled_with_valid_id(self):
        self.assertContains(self.client.get("/"), f'data-ga-id="{GA}"')

    def test_invalid_ids_are_ignored(self):
        for bad in ["bad", "G-", "UA-123456", 'G-"><script>', "G-abcd1234"]:
            with self.subTest(bad=bad), self.settings(GA_MEASUREMENT_ID=bad):
                self.assertContains(self.client.get("/"), 'data-ga-id=""')

    @override_settings(GA_MEASUREMENT_ID=GA)
    def test_dashboard_never_loads_analytics(self):
        self.assertNotContains(self.client.get("/owner/login/"), "analytics.js")
        self.assertNotContains(self.client.get("/django-admin/login/"), "analytics.js")

    def test_add_button_carries_item_data(self):
        named("Alpha Milk", "80.00", 5)
        response = self.client.get("/products/")
        self.assertContains(response, 'data-name="Alpha Milk 1 litre"')
        self.assertContains(response, 'data-price="80.00"')

    @override_settings(GA_MEASUREMENT_ID=GA)
    def test_view_item_data_on_product_page(self):
        v = named("Alpha Milk", "80.00", 5)
        html = self.client.get(f"/products/{v.product.slug}/").content.decode()
        raw = re.search(r'<script id="ga-view-item" type="application/json">(.*?)</script>', html, re.S).group(1)
        data = json.loads(raw)
        self.assertEqual(data["currency"], "KES")
        self.assertEqual(data["items"][0]["item_id"], str(v.id))
        self.assertEqual(data["items"][0]["price"], 80.0)

    def test_no_view_item_data_when_disabled(self):
        v = named("Alpha Milk", "80.00", 5)
        self.assertNotContains(self.client.get(f"/products/{v.product.slug}/"), "ga-view-item")

    @override_settings(GA_MEASUREMENT_ID=GA)
    def test_purchase_data_has_no_personal_information(self):
        order = placed()
        html = self.client.get(f"/order/{order.public_token}/").content.decode()
        raw = re.search(r'<script id="ga-purchase" type="application/json">(.*?)</script>', html, re.S).group(1)
        data = json.loads(raw)
        self.assertEqual(data["transaction_id"], order.reference)
        self.assertEqual(data["currency"], "KES")
        self.assertEqual(data["value"], 160.0)
        self.assertEqual(data["items"][0]["quantity"], 2)
        for secret in ("Jane", "Wanjiku", "712345678", "Ndagani", "Blue gate", order.public_token):
            self.assertNotIn(secret, raw)

    def test_no_purchase_data_when_disabled(self):
        order = placed()
        self.assertNotContains(self.client.get(f"/order/{order.public_token}/"), "ga-purchase")

    @override_settings(PUBLIC_WHATSAPP_NUMBER="+254 712 345 678")
    def test_public_whatsapp_link(self):
        response = self.client.get("/")
        self.assertContains(response, 'href="https://wa.me/254712345678?text=Hello%20Royal%20Cream%20Dairy"')
        self.assertContains(response, 'data-track="whatsapp"')

    def test_no_whatsapp_link_by_default_or_when_invalid(self):
        self.assertNotContains(self.client.get("/"), "wa.me")
        with self.settings(PUBLIC_WHATSAPP_NUMBER="abc"):
            self.assertNotContains(self.client.get("/"), "wa.me")


@override_settings(**SEO)
class PrivacyPageTests(TestCase):
    def test_page_content(self):
        response = self.client.get("/privacy/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Privacy policy")
        self.assertContains(response, "WhatsApp")
        self.assertContains(response, "Data Protection Act, 2019")
        self.assertContains(response, "Office of the Data Protection Commissioner")

    @override_settings(PERSONAL_DATA_RETENTION_MONTHS=18)
    def test_retention_comes_from_settings(self):
        self.assertContains(self.client.get("/privacy/"), "18 months")

    @override_settings(PRIVACY_CONTACT_EMAIL="privacy@shop.test")
    def test_contact_email_shown_when_set(self):
        self.assertContains(self.client.get("/privacy/"), 'href="mailto:privacy@shop.test"')

    def test_no_contact_text_when_not_set(self):
        self.assertNotContains(self.client.get("/privacy/"), "mailto:")

    def test_analytics_is_disclosed_only_when_enabled(self):
        self.assertNotContains(self.client.get("/privacy/"), "Google Analytics")
        with self.settings(GA_MEASUREMENT_ID=GA):
            self.assertContains(self.client.get("/privacy/"), "Google Analytics")

    def test_linked_from_footer_and_checkout(self):
        self.assertContains(self.client.get("/"), 'href="/privacy/"')
        self.assertContains(self.client.get("/checkout/"), 'href="/privacy/"')


@override_settings(**SEO)
class PrivacyToolsTests(TestCase):
    def test_open_orders_block_anonymisation(self):
        order = placed()
        with self.assertRaises(privacy.OpenOrdersError):
            privacy.anonymize_customer(order.customer)
        order.customer.refresh_from_db()
        self.assertEqual(order.customer.name, "Jane Wanjiku")

    def test_anonymise_removes_personal_data_but_keeps_totals(self):
        order = placed(consent=True)
        complete(order)
        self.assertTrue(privacy.anonymize_customer(order.customer))
        customer = Customer.objects.get(pk=order.customer_id)
        self.assertEqual(customer.name, "Anonymised customer")
        self.assertTrue(customer.phone.startswith("anon-"))
        self.assertFalse(customer.whatsapp_opt_in)
        self.assertIsNone(customer.whatsapp_consent_at)
        order.refresh_from_db()
        self.assertEqual((order.delivery_address, order.delivery_instructions), ("", ""))
        self.assertEqual(order.delivery_area, "Ndagani")
        self.assertEqual(order.total, Decimal("160.00"))
        for note in Notification.objects.filter(order=order):
            self.assertEqual(note.params, [])
            self.assertEqual(note.recipient_phone, "")
            self.assertEqual(note.status, "SKIPPED")

    def test_second_anonymisation_is_a_no_op(self):
        order = placed()
        complete(order)
        privacy.anonymize_customer(order.customer)
        self.assertFalse(privacy.anonymize_customer(order.customer))

    def test_customer_can_order_again_with_same_phone_after_deletion(self):
        order = placed()
        complete(order)
        privacy.anonymize_customer(order.customer)
        again = placed()
        self.assertEqual(again.customer.phone, "+254712345678")
        self.assertNotEqual(again.customer_id, order.customer_id)

    def test_anonymise_command(self):
        order = placed()
        complete(order)
        out = StringIO()
        call_command("anonymize_customer", "--phone", "0712 345 678", "--yes", stdout=out)
        self.assertIn("Anonymised", out.getvalue())
        self.assertTrue(Customer.objects.get(pk=order.customer_id).phone.startswith("anon-"))

    def test_anonymise_command_needs_confirmation_and_valid_input(self):
        order = placed()
        complete(order)
        with self.assertRaises(CommandError):
            call_command("anonymize_customer", "--phone", "0712345678")
        with self.assertRaises(CommandError):
            call_command("anonymize_customer", "--phone", "12345", "--yes")
        with self.assertRaises(CommandError):
            call_command("anonymize_customer", "--phone", "0799999999", "--yes")
        self.assertEqual(Customer.objects.get(pk=order.customer_id).name, "Jane Wanjiku")

    def test_anonymise_command_refuses_open_orders(self):
        placed()
        with self.assertRaises(CommandError):
            call_command("anonymize_customer", "--phone", "0712345678", "--yes")

    def test_purge_removes_only_old_customers(self):
        milk = make_variant("80.00", 200)
        old = placed(milk=milk)
        complete(old)
        Order.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=800))
        recent_order = order_services.place_order(
            items=[{"variant_id": milk.id, "quantity": 1}], name="Brian Otieno", phone="0733000222",
            whatsapp_consent=False, delivery_area="Chuka", delivery_address="Main road",
            idempotency_key=uuid.uuid4().hex,
        )[0]
        complete(recent_order)
        out = StringIO()
        call_command("purge_personal_data", "--months", "24", stdout=out)
        self.assertIn("Anonymised 1 customer(s)", out.getvalue())
        self.assertTrue(Customer.objects.get(pk=old.customer_id).phone.startswith("anon-"))
        self.assertEqual(Customer.objects.get(pk=recent_order.customer_id).name, "Brian Otieno")

    def test_purge_dry_run_changes_nothing(self):
        old = placed()
        complete(old)
        Order.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=800))
        out = StringIO()
        call_command("purge_personal_data", "--months", "24", "--dry-run", stdout=out)
        self.assertIn("Would anonymise 1", out.getvalue())
        self.assertEqual(Customer.objects.get(pk=old.customer_id).name, "Jane Wanjiku")

    def test_purge_skips_customers_with_open_orders(self):
        old = placed()
        Order.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=800))
        out = StringIO()
        call_command("purge_personal_data", "--months", "24", stdout=out)
        self.assertIn("skipped 1", out.getvalue())
        self.assertEqual(Customer.objects.get(pk=old.customer_id).name, "Jane Wanjiku")

    def test_purge_rejects_bad_months(self):
        with self.assertRaises(CommandError):
            call_command("purge_personal_data", "--months", "0")


class SystemCheckTests(TestCase):
    PROD = {"DJANGO_SETTINGS_MODULE": "config.settings.production"}

    @override_settings(DEBUG=False, PRIVACY_CONTACT_EMAIL="")
    def test_warns_in_production_without_contact(self):
        with mock.patch.dict(os.environ, self.PROD):
            found = checks.privacy_contact_configured(None)
        self.assertEqual([m.id for m in found], ["royalcream.W001"])

    @override_settings(DEBUG=False, PRIVACY_CONTACT_EMAIL="privacy@shop.test")
    def test_quiet_when_contact_is_set(self):
        with mock.patch.dict(os.environ, self.PROD):
            self.assertEqual(checks.privacy_contact_configured(None), [])

    @override_settings(DEBUG=False, PRIVACY_CONTACT_EMAIL="")
    def test_quiet_outside_production(self):
        with mock.patch.dict(os.environ, {"DJANGO_SETTINGS_MODULE": "config.settings.development"}):
            self.assertEqual(checks.privacy_contact_configured(None), [])