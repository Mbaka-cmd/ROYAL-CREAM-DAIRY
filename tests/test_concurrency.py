import threading
import uuid
from unittest import skipUnless

from django.db import connection, connections
from django.test import TransactionTestCase, override_settings

from apps.inventory.models import Inventory
from apps.orders import services
from apps.orders.models import Order
from tests.helpers import make_variant


@skipUnless(connection.vendor == "postgresql", "Row-level locking test needs PostgreSQL (SQLite is skipped).")
@override_settings(WHATSAPP_ACCESS_TOKEN="")
class LastUnitConcurrencyTests(TransactionTestCase):
    def test_two_customers_cannot_both_buy_the_last_unit(self):
        variant = make_variant("80.00", 1)
        barrier = threading.Barrier(2)
        results = []

        def worker(phone):
            try:
                barrier.wait(timeout=10)
                services.place_order(
                    items=[{"variant_id": variant.id, "quantity": 1}],
                    name="Buyer", phone=phone, whatsapp_consent=False,
                    delivery_area="Chuka", delivery_address="Main road",
                    idempotency_key=uuid.uuid4().hex,
                )
                results.append("ok")
            except services.InsufficientStock:
                results.append("insufficient")
            except Exception as exc:  # pragma: no cover
                results.append(f"error: {exc!r}")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(p,)) for p in ("0712345678", "0723456789")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(sorted(results), ["insufficient", "ok"])
        row = Inventory.objects.get(variant=variant)
        self.assertEqual((row.quantity_on_hand, row.quantity_reserved), (1, 1))
        self.assertEqual(Order.objects.count(), 1)