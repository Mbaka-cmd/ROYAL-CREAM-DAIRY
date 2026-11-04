import io
import shutil
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, Permission, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.accounts import roles
from apps.catalogue.models import Category, Product, ProductVariant
from apps.inventory import services as inv
from apps.inventory.models import Inventory, StockMovement
from apps.notifications.models import Notification
from apps.orders import services as order_services
from apps.orders.models import Order
from tests.helpers import make_variant

PASSWORD = "S3cure-Pass-Phrase!"
FAST_HASHER = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def make_user(username, role=None, superuser=False, active=True):
    if superuser:
        user = User.objects.create_superuser(username, f"{username}@example.com", PASSWORD)
    else:
        user = User.objects.create_user(username, f"{username}@example.com", PASSWORD)
    if role:
        user.groups.add(Group.objects.get(name=role))
    if not active:
        user.is_active = False
        user.save()
    return user


def make_order(milk=None, qty=1, consent=False, phone="0712345678", name="Jane Wanjiku"):
    milk = milk or make_variant("80.00", 100)
    order, _ = order_services.place_order(
        items=[{"variant_id": milk.id, "quantity": qty}],
        name=name, phone=phone, whatsapp_consent=consent,
        delivery_area="Ndagani", delivery_address="Near the market",
        idempotency_key=uuid.uuid4().hex,
    )
    return order


def complete(order):
    for status in ["CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY", "COMPLETED"]:
        order_services.change_status(order.pk, status)


@override_settings(
    DELIVERY_FEE=Decimal("0.00"),
    PASSWORD_HASHERS=FAST_HASHER,
    LOGIN_RATE_LIMIT="1000/m",
    LOGIN_USER_RATE_LIMIT="1000/m",
)
class DashboardBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles.ensure_roles()
        cls.owner = make_user("owner", superuser=True)
        cls.order_mgr = make_user("orders", roles.ROLE_ORDER_MANAGER)
        cls.inv_mgr = make_user("stock", roles.ROLE_INVENTORY_MANAGER)
        cls.nobody = make_user("nobody")

    def setUp(self):
        cache.clear()

    def login(self, user):
        self.client.force_login(user)


def codes_for(group_name):
    group = Group.objects.get(name=group_name)
    return {f"{p.content_type.app_label}.{p.codename}" for p in group.permissions.select_related("content_type")}


class RoleTests(DashboardBase):
    def test_groups_exist(self):
        self.assertEqual(set(Group.objects.filter(name__in=roles.ROLE_NAMES).values_list("name", flat=True)), set(roles.ROLE_NAMES))

    def test_order_manager_permissions(self):
        codes = codes_for(roles.ROLE_ORDER_MANAGER)
        self.assertIn("orders.change_order", codes)
        self.assertIn("notifications.change_notification", codes)
        self.assertNotIn("catalogue.change_productvariant", codes)
        self.assertNotIn("inventory.change_inventory", codes)
        self.assertNotIn("auth.change_user", codes)

    def test_inventory_manager_permissions(self):
        codes = codes_for(roles.ROLE_INVENTORY_MANAGER)
        self.assertIn("inventory.change_inventory", codes)
        self.assertIn("catalogue.change_productvariant", codes)
        self.assertNotIn("orders.change_order", codes)
        self.assertNotIn("auth.change_user", codes)

    def test_owner_has_every_business_permission_but_no_user_admin(self):
        owner = Group.objects.get(name=roles.ROLE_OWNER)
        business = Permission.objects.filter(content_type__app_label__in=roles.BUSINESS_APPS).count()
        self.assertEqual(owner.permissions.count(), business)
        self.assertNotIn("auth.change_user", codes_for(roles.ROLE_OWNER))

    def test_ensure_roles_is_idempotent(self):
        before = {g.name: g.permissions.count() for g in Group.objects.filter(name__in=roles.ROLE_NAMES)}
        roles.ensure_roles()
        roles.ensure_roles()
        after = {g.name: g.permissions.count() for g in Group.objects.filter(name__in=roles.ROLE_NAMES)}
        self.assertEqual(before, after)

    def test_manual_permissions_survive_ensure_roles(self):
        group = Group.objects.get(name=roles.ROLE_ORDER_MANAGER)
        extra = Permission.objects.get(content_type__app_label="auth", codename="view_user")
        group.permissions.add(extra)
        roles.ensure_roles()
        self.assertIn("auth.view_user", codes_for(roles.ROLE_ORDER_MANAGER))

    def test_dashboard_access_helper(self):
        self.assertTrue(roles.has_dashboard_access(self.owner))
        self.assertTrue(roles.has_dashboard_access(self.order_mgr))
        self.assertFalse(roles.has_dashboard_access(self.nobody))

    def test_setup_roles_command(self):
        from io import StringIO

        out = StringIO()
        call_command("setup_roles", stdout=out)
        self.assertIn("Roles ready", out.getvalue())


class CreateStaffCommandTests(DashboardBase):
    PATCH = "apps.accounts.management.commands.create_staff.getpass.getpass"

    def test_creates_user_in_role(self):
        with mock.patch(self.PATCH, return_value=PASSWORD):
            call_command("create_staff", username="amina", role=roles.ROLE_ORDER_MANAGER)
        user = User.objects.get(username="amina")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.is_staff)
        self.assertTrue(user.groups.filter(name=roles.ROLE_ORDER_MANAGER).exists())

    def test_owner_role_gets_admin_access(self):
        with mock.patch(self.PATCH, return_value=PASSWORD):
            call_command("create_staff", username="boss", role=roles.ROLE_OWNER)
        self.assertTrue(User.objects.get(username="boss").is_staff)

    def test_weak_password_rejected(self):
        with mock.patch(self.PATCH, return_value="123"):
            with self.assertRaises(CommandError):
                call_command("create_staff", username="weak", role=roles.ROLE_ORDER_MANAGER)
        self.assertFalse(User.objects.filter(username="weak").exists())

    def test_mismatched_passwords_rejected(self):
        with mock.patch(self.PATCH, side_effect=[PASSWORD, "Different-Pass-123!"]):
            with self.assertRaises(CommandError):
                call_command("create_staff", username="mismatch", role=roles.ROLE_ORDER_MANAGER)

    def test_duplicate_username_rejected(self):
        with mock.patch(self.PATCH, return_value=PASSWORD):
            with self.assertRaises(CommandError):
                call_command("create_staff", username="owner", role=roles.ROLE_ORDER_MANAGER)


class AccessTests(DashboardBase):
    PROTECTED = [
        "/owner/", "/owner/orders/", "/owner/inventory/", "/owner/products/",
        "/owner/products/new/", "/owner/notifications/", "/owner/reports/",
    ]

    def test_anonymous_is_redirected_to_login(self):
        for url in self.PROTECTED:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/owner/login/?next="))

    def test_user_without_role_is_forbidden(self):
        self.login(self.nobody)
        for url in self.PROTECTED:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_owner_can_open_everything(self):
        self.login(self.owner)
        for url in self.PROTECTED:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_order_manager_scope(self):
        self.login(self.order_mgr)
        for url in ["/owner/", "/owner/orders/", "/owner/notifications/", "/owner/reports/", "/owner/inventory/", "/owner/products/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get("/owner/products/new/").status_code, 403)

    def test_inventory_manager_scope(self):
        self.login(self.inv_mgr)
        for url in ["/owner/", "/owner/inventory/", "/owner/products/", "/owner/products/new/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        for url in ["/owner/orders/", "/owner/notifications/", "/owner/reports/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_write_endpoints_enforce_permissions(self):
        order = make_order()
        variant = make_variant("80.00", 5)
        self.login(self.order_mgr)
        self.assertEqual(self.client.post("/owner/inventory/adjust/", {"variant": variant.pk, "action": "receive", "quantity": 1}).status_code, 403)
        self.assertEqual(self.client.get(f"/owner/products/{variant.product_id}/update/").status_code, 403)
        self.client.logout()
        self.login(self.inv_mgr)
        self.assertEqual(self.client.post(f"/owner/orders/{order.pk}/status/", {"status": "CONFIRMED"}).status_code, 403)
        self.assertEqual(self.client.post("/owner/notifications/1/retry/").status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, "NEW")

    def test_anonymous_post_is_redirected_not_executed(self):
        order = make_order()
        response = self.client.post(f"/owner/orders/{order.pk}/status/", {"status": "CONFIRMED"})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "NEW")

    def test_pages_are_not_cached(self):
        self.login(self.owner)
        self.assertIn("no-store", self.client.get("/owner/")["Cache-Control"])

    def test_csrf_enforced_on_dashboard_posts(self):
        order = make_order()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(f"/owner/orders/{order.pk}/status/", {"status": "CONFIRMED"}).status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, "NEW")

    def test_custom_404_page(self):
        self.login(self.owner)
        response = self.client.get("/owner/orders/999999/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Page not found", status_code=404)


class LoginTests(DashboardBase):
    def test_successful_login(self):
        response = self.client.post("/owner/login/", {"username": "owner", "password": PASSWORD})
        self.assertRedirects(response, "/owner/")

    def test_wrong_password(self):
        response = self.client.post("/owner/login/", {"username": "owner", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "correct username and password")
        self.assertEqual(self.client.get("/owner/").status_code, 302)

    def test_account_without_role_cannot_log_in(self):
        response = self.client.post("/owner/login/", {"username": "nobody", "password": PASSWORD})
        self.assertContains(response, "does not have dashboard access")
        self.assertEqual(self.client.get("/owner/").status_code, 302)

    def test_inactive_user_cannot_log_in(self):
        make_user("ghost", roles.ROLE_ORDER_MANAGER, active=False)
        response = self.client.post("/owner/login/", {"username": "ghost", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/owner/").status_code, 302)

    def test_external_next_is_ignored(self):
        response = self.client.post(
            "/owner/login/", {"username": "owner", "password": PASSWORD, "next": "https://evil.example/steal"}
        )
        self.assertEqual(response["Location"], "/owner/")

    def test_internal_next_is_honoured(self):
        response = self.client.post(
            "/owner/login/", {"username": "owner", "password": PASSWORD, "next": "/owner/orders/"}
        )
        self.assertEqual(response["Location"], "/owner/orders/")

    def test_rate_limited_by_ip(self):
        with self.settings(LOGIN_RATE_LIMIT="2/m"):
            cache.clear()
            codes = [
                self.client.post("/owner/login/", {"username": "owner", "password": "bad"}).status_code
                for _ in range(3)
            ]
            self.assertEqual(codes, [200, 200, 429])
            blocked = self.client.post("/owner/login/", {"username": "owner", "password": PASSWORD})
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(self.client.get("/owner/").status_code, 302)

    def test_rate_limited_by_username_across_ips(self):
        with self.settings(LOGIN_USER_RATE_LIMIT="2/m"):
            cache.clear()
            codes = [
                self.client.post(
                    "/owner/login/", {"username": "owner", "password": "bad"}, REMOTE_ADDR=f"10.0.0.{i}"
                ).status_code
                for i in range(1, 4)
            ]
        self.assertEqual(codes, [200, 200, 429])

    def test_failed_login_is_logged_without_the_password(self):
        with self.assertLogs("apps.accounts", level="WARNING") as logs:
            self.client.post("/owner/login/", {"username": "owner", "password": "super-secret-guess"})
        joined = " ".join(logs.output)
        self.assertIn("Failed login", joined)
        self.assertNotIn("super-secret-guess", joined)

    def test_logout_requires_post(self):
        self.login(self.owner)
        self.assertEqual(self.client.get("/owner/logout/").status_code, 405)
        self.assertEqual(self.client.get("/owner/").status_code, 200)
        response = self.client.post("/owner/logout/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/owner/").status_code, 302)

    def test_login_page_redirects_when_already_signed_in(self):
        self.login(self.owner)
        self.assertEqual(self.client.get("/owner/login/").status_code, 302)

    def test_login_form_has_csrf_protection(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post("/owner/login/", {"username": "owner", "password": PASSWORD}).status_code, 403)


class HomeTests(DashboardBase):
    def test_order_counts(self):
        make_order()
        second = make_order()
        order_services.change_status(second.pk, "CONFIRMED")
        self.login(self.owner)
        counts = self.client.get("/owner/").context["orders"]
        self.assertEqual((counts["new"], counts["confirmed"]), (1, 1))

    def test_completed_today(self):
        complete(make_order())
        self.login(self.owner)
        self.assertEqual(self.client.get("/owner/").context["orders"]["completed_today"], 1)

    def test_stock_counts(self):
        make_variant("80.00", 3)    # low (threshold 5)
        make_variant("80.00", 0)    # no stock row: out
        make_variant("80.00", 50)   # fine
        self.login(self.owner)
        stock = self.client.get("/owner/").context["stock"]
        self.assertEqual((stock["low"], stock["out"]), (1, 1))

    def test_notification_counts(self):
        make_order(consent=True)
        self.login(self.owner)
        Notification.objects.update(created_at=timezone.now() - timedelta(minutes=20))
        counts = self.client.get("/owner/").context["notifications"]
        self.assertEqual((counts["needs_review"], counts["unsent"]), (0, 2))
        Notification.objects.update(status="FAILED")
        counts = self.client.get("/owner/").context["notifications"]
        self.assertEqual((counts["needs_review"], counts["unsent"]), (2, 0))

    def test_widgets_follow_permissions(self):
        self.login(self.inv_mgr)
        context = self.client.get("/owner/").context
        self.assertIsNone(context["orders"])
        self.assertIsNone(context["notifications"])
        self.assertIsNotNone(context["stock"])


class OrderListTests(DashboardBase):
    def setUp(self):
        super().setUp()
        self.login(self.owner)

    def test_status_filter(self):
        a = make_order()
        make_order()
        order_services.change_status(a.pk, "CONFIRMED")
        page = self.client.get("/owner/orders/?status=CONFIRMED").context["page"]
        self.assertEqual([o.pk for o in page.object_list], [a.pk])

    def test_unknown_status_is_ignored(self):
        make_order()
        make_order()
        page = self.client.get("/owner/orders/?status=BOGUS").context["page"]
        self.assertEqual(len(page.object_list), 2)

    def test_search_by_reference_name_and_phone(self):
        a = make_order(name="Amina Said", phone="0722000111")
        b = make_order(name="Brian Otieno", phone="0733000222")
        by_ref = self.client.get("/owner/orders/", {"q": a.reference}).context["page"]
        self.assertEqual([o.pk for o in by_ref.object_list], [a.pk])
        by_name = self.client.get("/owner/orders/", {"q": "otieno"}).context["page"]
        self.assertEqual([o.pk for o in by_name.object_list], [b.pk])
        by_phone = self.client.get("/owner/orders/", {"q": "0733 000 222"}).context["page"]
        self.assertEqual([o.pk for o in by_phone.object_list], [b.pk])

    def test_pagination(self):
        milk = make_variant("80.00", 200)
        for _ in range(21):
            make_order(milk=milk)
        page = self.client.get("/owner/orders/").context["page"]
        self.assertEqual((page.paginator.num_pages, len(page.object_list)), (2, 20))
        self.assertEqual(len(self.client.get("/owner/orders/?page=2").context["page"].object_list), 1)
        self.assertEqual(self.client.get("/owner/orders/?page=zzz").status_code, 200)


class OrderDetailTests(DashboardBase):
    def test_detail_shows_everything_the_owner_needs(self):
        order = make_order(consent=True, qty=2)
        self.login(self.owner)
        response = self.client.get(f"/owner/orders/{order.pk}/")
        self.assertContains(response, order.reference)
        self.assertContains(response, "+254712345678")
        self.assertContains(response, "Near the market")
        self.assertContains(response, "Order received")
        self.assertContains(response, "KSh 160")

    def test_unknown_order_is_404(self):
        self.login(self.owner)
        self.assertEqual(self.client.get("/owner/orders/999999/").status_code, 404)

    def test_actions_hidden_without_change_permission(self):
        order = make_order()
        view_only = make_user("viewer", roles.ROLE_ORDER_MANAGER)
        view_only.groups.clear()
        extra = Permission.objects.get(content_type__app_label="orders", codename="view_order")
        view_only.user_permissions.add(extra)
        view_only.groups.add(Group.objects.get(name=roles.ROLE_INVENTORY_MANAGER))
        self.login(view_only)
        response = self.client.get(f"/owner/orders/{order.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Confirm order")


class OrderStatusViewTests(DashboardBase):
    def setUp(self):
        super().setUp()
        self.milk = make_variant("80.00", 100)
        self.order = make_order(milk=self.milk, qty=2)
        self.login(self.order_mgr)

    def post(self, status, note=""):
        return self.client.post(f"/owner/orders/{self.order.pk}/status/", {"status": status, "note": note}, follow=True)

    def test_confirm(self):
        response = self.post("CONFIRMED")
        self.assertContains(response, "is now Confirmed")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "CONFIRMED")
        history = self.order.status_history.last()
        self.assertEqual(history.changed_by, self.order_mgr)

    def test_full_flow_deducts_stock(self):
        for status in ["CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY", "COMPLETED"]:
            self.post(status)
        row = Inventory.objects.get(variant=self.milk)
        self.assertEqual((row.quantity_on_hand, row.quantity_reserved), (98, 0))

    def test_invalid_transition_shows_error_and_changes_nothing(self):
        response = self.post("COMPLETED")
        self.assertContains(response, "Cannot change order")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "NEW")

    def test_double_click_is_handled(self):
        self.post("CONFIRMED")
        response = self.post("CONFIRMED")
        self.assertContains(response, "Cannot change order")
        self.assertEqual(self.order.status_history.count(), 2)

    def test_cancel_needs_reason(self):
        response = self.post("CANCELLED", note="  ")
        self.assertContains(response, "reason is required")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "NEW")
        self.assertEqual(Inventory.objects.get(variant=self.milk).quantity_reserved, 2)

    def test_cancel_with_reason_releases_stock(self):
        self.post("CANCELLED", note="Customer changed mind")
        self.order.refresh_from_db()
        self.assertEqual((self.order.status, self.order.cancel_reason), ("CANCELLED", "Customer changed mind"))
        self.assertEqual(Inventory.objects.get(variant=self.milk).quantity_reserved, 0)

    def test_unknown_status_value(self):
        response = self.post("SHIPPED")
        self.assertContains(response, "Unknown status")

    def test_unknown_order_is_404(self):
        response = self.client.post("/owner/orders/999999/status/", {"status": "CONFIRMED"})
        self.assertEqual(response.status_code, 404)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(f"/owner/orders/{self.order.pk}/status/").status_code, 405)


class InventoryViewTests(DashboardBase):
    def setUp(self):
        super().setUp()
        self.login(self.inv_mgr)

    def post(self, variant, action, quantity, reason=""):
        return self.client.post(
            "/owner/inventory/adjust/",
            {"variant": variant.pk, "action": action, "quantity": quantity, "reason": reason},
        )

    def test_receive_stock_records_user_and_default_reason(self):
        v = make_variant("80.00", 0)
        response = self.post(v, "receive", 12)
        self.assertRedirects(response, "/owner/inventory/")
        self.assertEqual(Inventory.objects.get(variant=v).quantity_on_hand, 12)
        movement = StockMovement.objects.get(variant=v)
        self.assertEqual((movement.movement_type, movement.created_by, movement.reason), ("RECEIVE", self.inv_mgr, "Stock received"))

    def test_adjust_up_and_down(self):
        v = make_variant("80.00", 10)
        self.post(v, "adjust_up", 5, "found extra crate")
        self.post(v, "adjust_down", 3, "spilled")
        self.assertEqual(Inventory.objects.get(variant=v).quantity_on_hand, 12)
        self.assertEqual(StockMovement.objects.filter(variant=v, movement_type="ADJUST").count(), 2)

    def test_adjustment_without_reason_is_rejected(self):
        v = make_variant("80.00", 10)
        response = self.post(v, "adjust_down", 3, "")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Inventory.objects.get(variant=v).quantity_on_hand, 10)

    def test_cannot_go_below_reserved(self):
        v = make_variant("80.00", 10)
        inv.reserve_stock({v.id: 6}, reference="RC-X")
        response = self.post(v, "adjust_down", 5, "count correction")
        self.assertContains(response, "reserved", status_code=400)
        self.assertEqual(Inventory.objects.get(variant=v).quantity_on_hand, 10)

    def test_waste_needs_reason_and_reduces_stock(self):
        v = make_variant("80.00", 10)
        self.assertEqual(self.post(v, "waste", 2, "").status_code, 400)
        self.assertEqual(self.post(v, "waste", 2, "expired").status_code, 302)
        self.assertEqual(Inventory.objects.get(variant=v).quantity_on_hand, 8)

    def test_bad_quantities_rejected(self):
        v = make_variant("80.00", 10)
        for qty in ["0", "-1", "abc", ""]:
            with self.subTest(qty=qty):
                self.assertEqual(self.post(v, "receive", qty).status_code, 400)
        self.assertEqual(Inventory.objects.get(variant=v).quantity_on_hand, 10)

    def test_inactive_variant_rejected(self):
        v = make_variant("80.00", 10)
        v.is_active = False
        v.save()
        self.assertEqual(self.post(v, "receive", 1).status_code, 400)

    def test_bad_action_rejected(self):
        v = make_variant("80.00", 10)
        self.assertEqual(self.post(v, "steal", 1).status_code, 400)

    def test_prefill_from_query(self):
        v = make_variant("80.00", 10)
        response = self.client.get(f"/owner/inventory/?variant={v.pk}")
        self.assertEqual(response.context["form"].initial["variant"], v.pk)

    def test_filters(self):
        low = make_variant("80.00", 3)
        out = make_variant("80.00", 0)
        ok = make_variant("80.00", 50)
        low_ids = [r.pk for r in self.client.get("/owner/inventory/?filter=low").context["rows"]]
        out_ids = [r.pk for r in self.client.get("/owner/inventory/?filter=out").context["rows"]]
        all_ids = [r.pk for r in self.client.get("/owner/inventory/").context["rows"]]
        self.assertEqual(low_ids, [low.pk])
        self.assertEqual(out_ids, [out.pk])
        self.assertEqual(set(all_ids), {low.pk, out.pk, ok.pk})

    def test_status_labels(self):
        low = make_variant("80.00", 3)
        out = make_variant("80.00", 0)
        ok = make_variant("80.00", 50)
        rows = {r.pk: r.stock_status for r in self.client.get("/owner/inventory/").context["rows"]}
        self.assertEqual(rows, {low.pk: "Low stock", out.pk: "Out of stock", ok.pk: "In stock"})

    def test_recent_movements_listed(self):
        v = make_variant("80.00", 0)
        self.post(v, "receive", 4)
        response = self.client.get("/owner/inventory/")
        self.assertContains(response, "Received")
        self.assertContains(response, "stock")


class ProductDashboardTests(DashboardBase):
    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(name="Dairy", slug="dairy")
        self.login(self.inv_mgr)

    def create_data(self, **over):
        data = {
            "category": self.category.pk, "name": "Fresh Milk", "slug": "", "description": "Fresh", "is_active": "on",
            "variants-TOTAL_FORMS": "2", "variants-INITIAL_FORMS": "0",
            "variants-MIN_NUM_FORMS": "1", "variants-MAX_NUM_FORMS": "1000",
            "variants-0-name": "1 litre", "variants-0-price": "80.00", "variants-0-unit": "L", "variants-0-is_active": "on",
            "variants-1-name": "", "variants-1-price": "", "variants-1-unit": "", "variants-1-is_active": "on",
        }
        data.update(over)
        return data

    def update_data(self, product, **over):
        variants = list(product.variants.order_by("id"))
        data = {
            "category": product.category_id, "name": product.name, "slug": product.slug,
            "description": product.description, "is_active": "on" if product.is_active else "",
            "variants-TOTAL_FORMS": str(len(variants) + 1), "variants-INITIAL_FORMS": str(len(variants)),
            "variants-MIN_NUM_FORMS": "1", "variants-MAX_NUM_FORMS": "1000",
        }
        for i, v in enumerate(variants):
            data.update({
                f"variants-{i}-id": v.pk, f"variants-{i}-product": product.pk, f"variants-{i}-name": v.name,
                f"variants-{i}-price": str(v.price), f"variants-{i}-unit": v.unit,
                f"variants-{i}-is_active": "on" if v.is_active else "",
            })
        n = len(variants)
        data.update({f"variants-{n}-id": "", f"variants-{n}-product": product.pk,
                     f"variants-{n}-name": "", f"variants-{n}-price": "", f"variants-{n}-unit": "", f"variants-{n}-is_active": "on"})
        data.update(over)
        return data

    def image(self, fmt="PNG", name="p.png"):
        buffer = io.BytesIO()
        Image.new("RGB", (20, 20), "red").save(buffer, fmt)
        return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{fmt.lower()}")

    def make_product(self):
        response = self.client.post("/owner/products/new/", self.create_data())
        self.assertEqual(response.status_code, 302)
        return Product.objects.get(name="Fresh Milk")

    def test_create_product_with_variant(self):
        response = self.client.post("/owner/products/new/", self.create_data())
        self.assertRedirects(response, "/owner/products/")
        product = Product.objects.get()
        self.assertEqual(product.slug, "fresh-milk")
        self.assertEqual(product.variants.get().price, Decimal("80.00"))

    def test_slug_is_made_unique_automatically(self):
        self.client.post("/owner/products/new/", self.create_data())
        self.client.post("/owner/products/new/", self.create_data())
        self.assertEqual(sorted(Product.objects.values_list("slug", flat=True)), ["fresh-milk", "fresh-milk-2"])

    def test_explicit_duplicate_slug_rejected(self):
        self.client.post("/owner/products/new/", self.create_data())
        response = self.client.post("/owner/products/new/", self.create_data(name="Other", slug="fresh-milk"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Product.objects.count(), 1)

    def test_product_needs_at_least_one_variant(self):
        response = self.client.post("/owner/products/new/", self.create_data(**{"variants-0-name": "", "variants-0-price": ""}))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Product.objects.count(), 0)

    def test_bad_prices_rejected(self):
        for price in ["0", "-5", "abc"]:
            with self.subTest(price=price):
                response = self.client.post("/owner/products/new/", self.create_data(**{"variants-0-price": price}))
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Product.objects.count(), 0)

    def test_duplicate_variant_names_do_not_crash(self):
        data = self.create_data(**{"variants-1-name": "1 litre", "variants-1-price": "90.00"})
        response = self.client.post("/owner/products/new/", data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Product.objects.count(), 0)

    def test_update_price_is_saved_and_logged(self):
        product = self.make_product()
        variant = product.variants.get()
        data = self.update_data(product, **{"variants-0-price": "95.00"})
        with self.assertLogs("apps.dashboard", level="INFO") as logs:
            response = self.client.post(f"/owner/products/{product.pk}/update/", data)
        self.assertRedirects(response, "/owner/products/")
        variant.refresh_from_db()
        self.assertEqual(variant.price, Decimal("95.00"))
        self.assertTrue(any("price changed" in line for line in logs.output))

    def test_update_can_add_a_variant(self):
        product = self.make_product()
        n = product.variants.count()
        data = self.update_data(product, **{f"variants-{n}-name": "500 ml", f"variants-{n}-price": "45.00"})
        self.client.post(f"/owner/products/{product.pk}/update/", data)
        self.assertEqual(product.variants.count(), 2)

    def test_hiding_a_product_removes_it_from_the_shop(self):
        product = self.make_product()
        inv.receive_stock(product.variants.get().id, 5, reason="test")
        self.assertContains(self.client.get("/products/"), "Fresh Milk")
        self.client.post(f"/owner/products/{product.pk}/update/", self.update_data(product, is_active=""))
        self.assertNotContains(self.client.get("/products/"), "Fresh Milk")

    def test_update_form_prefilled(self):
        product = self.make_product()
        response = self.client.get(f"/owner/products/{product.pk}/update/")
        self.assertContains(response, "Fresh Milk")
        self.assertContains(response, "80.00")

    def test_unknown_product_update_is_404(self):
        self.assertEqual(self.client.get("/owner/products/999999/update/").status_code, 404)

    def test_valid_image_is_stored(self):
        data = self.create_data(image=self.image())
        self.client.post("/owner/products/new/", data)
        product = Product.objects.get()
        self.assertTrue(product.image.name.startswith("products/"))
        self.assertTrue(product.image.storage.exists(product.image.name))

    def test_gif_image_rejected(self):
        response = self.client.post("/owner/products/new/", self.create_data(image=self.image("GIF", "p.gif")))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Product.objects.count(), 0)

    def test_non_image_rejected(self):
        fake = SimpleUploadedFile("p.png", b"not an image at all", content_type="image/png")
        response = self.client.post("/owner/products/new/", self.create_data(image=fake))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Product.objects.count(), 0)

    def test_oversized_image_rejected(self):
        with mock.patch("apps.dashboard.forms.MAX_IMAGE_BYTES", 10):
            response = self.client.post("/owner/products/new/", self.create_data(image=self.image()))
        self.assertContains(response, "too large", status_code=400)
        self.assertEqual(Product.objects.count(), 0)

    def test_product_list_search(self):
        self.make_product()
        other = make_variant("50.00", 5)
        other.product.name = "Mala"
        other.product.save()
        page = self.client.get("/owner/products/?q=mala").context["page"]
        self.assertEqual([p.name for p in page.object_list], ["Mala"])


class NotificationViewTests(DashboardBase):
    def setUp(self):
        super().setUp()
        self.order = make_order(consent=True)
        self.login(self.order_mgr)

    def test_list_and_filters(self):
        owner_note = Notification.objects.get(recipient_type="OWNER")
        Notification.objects.filter(pk=owner_note.pk).update(status="FAILED", last_error="131026 undeliverable")
        review = self.client.get("/owner/notifications/?status=review").context["page"]
        self.assertEqual([n.pk for n in review.object_list], [owner_note.pk])
        pending = self.client.get("/owner/notifications/?status=pending").context["page"]
        self.assertEqual(len(pending.object_list), 1)
        self.assertContains(self.client.get("/owner/notifications/"), "131026 undeliverable")

    def test_retry_requeues_failed_notification(self):
        note = Notification.objects.get(recipient_type="OWNER")
        Notification.objects.filter(pk=note.pk).update(status="FAILED", attempts=3, last_error="x")
        response = self.client.post(f"/owner/notifications/{note.pk}/retry/", follow=True)
        self.assertContains(response, "re-queued")
        note.refresh_from_db()
        self.assertEqual((note.status, note.attempts, note.last_error), ("PENDING", 0, ""))

    def test_retry_of_healthy_notification_does_nothing(self):
        note = Notification.objects.get(recipient_type="OWNER")
        Notification.objects.filter(pk=note.pk).update(status="SENT")
        response = self.client.post(f"/owner/notifications/{note.pk}/retry/", follow=True)
        self.assertContains(response, "No notifications were re-queued")
        note.refresh_from_db()
        self.assertEqual(note.status, "SENT")

    def test_retry_ignores_external_redirect_target(self):
        note = Notification.objects.get(recipient_type="OWNER")
        response = self.client.post(f"/owner/notifications/{note.pk}/retry/", {"next": "https://evil.example/"})
        self.assertEqual(response["Location"], "/owner/notifications/")

    def test_retry_returns_to_order_page(self):
        note = Notification.objects.get(recipient_type="OWNER")
        target = f"/owner/orders/{self.order.pk}/"
        response = self.client.post(f"/owner/notifications/{note.pk}/retry/", {"next": target})
        self.assertEqual(response["Location"], target)


class ReportTests(DashboardBase):
    def setUp(self):
        super().setUp()
        self.login(self.owner)

    def test_completed_orders_are_counted(self):
        milk = make_variant("80.00", 100)
        done = make_order(milk=milk, qty=2)
        complete(done)
        open_order = make_order(milk=milk, qty=1)
        cancelled = make_order(milk=milk, qty=1)
        order_services.change_status(cancelled.pk, "CANCELLED", note="test")
        response = self.client.get("/owner/reports/")
        self.assertEqual(response.context["totals"]["orders"], 1)
        self.assertEqual(response.context["totals"]["revenue"], Decimal("160.00"))
        self.assertEqual(len(response.context["daily"]), 1)
        top = response.context["top"]
        self.assertEqual((len(top), top[0]["units"]), (1, 2))
        self.assertEqual(open_order.status, "NEW")

    def test_date_range_filters(self):
        complete(make_order(qty=2))
        old = (timezone.localdate() - timedelta(days=10)).isoformat()
        older = (timezone.localdate() - timedelta(days=5)).isoformat()
        response = self.client.get("/owner/reports/", {"start": old, "end": older})
        self.assertEqual(response.context["totals"]["orders"], 0)
        self.assertEqual(response.context["totals"]["revenue"], 0)

    def test_bad_dates_fall_back_to_defaults(self):
        complete(make_order(qty=2))
        response = self.client.get("/owner/reports/", {"start": "nonsense", "end": "also-bad"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["totals"]["orders"], 1)

    def test_reversed_dates_are_swapped(self):
        today = timezone.localdate()
        response = self.client.get("/owner/reports/", {"start": today.isoformat(), "end": (today - timedelta(days=3)).isoformat()})
        self.assertLessEqual(response.context["start"], response.context["end"])

    def test_huge_ranges_are_capped(self):
        response = self.client.get("/owner/reports/", {"start": "2000-01-01", "end": "2026-11-03"})
        self.assertLessEqual((response.context["end"] - response.context["start"]).days, 366)