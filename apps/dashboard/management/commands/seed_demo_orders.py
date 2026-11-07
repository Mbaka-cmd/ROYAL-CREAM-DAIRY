from datetime import timedelta
from random import Random

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.catalogue.models import ProductVariant
from apps.customers.models import Customer
from apps.orders.models import Order, OrderItem, OrderStatusHistory

S = Order.Status
CHAIN = [S.NEW, S.CONFIRMED, S.PREPARING, S.OUT_FOR_DELIVERY, S.COMPLETED]
NAMES = ["Jane Wanjiku", "Peter Mwangi", "Grace Njeri", "John Kimathi", "Mercy Gitonga", "Brian Mutua",
         "Faith Kinyua", "Samuel Murithi", "Esther Karimi", "David Mugambi", "Ann Muthoni", "Kevin Njagi"]
PHONE_PREFIX = "+254710000"


class Command(BaseCommand):
    help = "Create demo orders (references DEMO-0001...) for the last 7 days. Development only."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Remove demo orders and demo customers.")
        parser.add_argument("--count", type=int, default=30)

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("Refusing to run: DEBUG is off.")
        with transaction.atomic():
            Order.objects.filter(reference__startswith="DEMO-").delete()
            Customer.objects.filter(phone__startswith=PHONE_PREFIX, orders__isnull=True).delete()
            if opts["clear"]:
                self.stdout.write("Demo data removed.")
                return
            variants = list(ProductVariant.objects.filter(is_active=True).select_related("product"))
            if not variants:
                raise CommandError("No products yet. Create products first.")
            try:
                from apps.delivery.models import DeliveryZone
                areas = list(DeliveryZone.objects.values_list("name", flat=True)) or None
            except Exception:
                areas = None
            areas = areas or ["Chuka Town", "Ndagani", "Kiangondu"]
            rng = Random(42)
            now = timezone.now()
            for i in range(1, opts["count"] + 1):
                days_ago = rng.choice([0, 0, 0, 1, 1, 2, 3, 4, 5, 6])
                created = now - timedelta(days=days_ago, minutes=rng.randint(20, 600))
                if days_ago >= 1:
                    final = S.CANCELLED if rng.random() < 0.1 else S.COMPLETED
                else:
                    final = rng.choice([S.NEW, S.NEW, S.CONFIRMED, S.PREPARING, S.OUT_FOR_DELIVERY, S.COMPLETED, S.COMPLETED])
                name = NAMES[(i - 1) % len(NAMES)]
                customer, _ = Customer.objects.get_or_create(
                    phone=f"{PHONE_PREFIX}{(i - 1) % len(NAMES):03d}", defaults={"name": name}
                )
                picks = rng.sample(variants, k=min(len(variants), rng.randint(1, 3)))
                lines = [(v, rng.randint(1, 3)) for v in picks]
                subtotal = sum(v.price * q for v, q in lines)
                fee = 50
                order = Order.objects.create(
                    reference=f"DEMO-{i:04d}", idempotency_key=f"demo-{i}", customer=customer,
                    delivery_area=rng.choice(areas), delivery_address="Demo address",
                    status=final, subtotal=subtotal, delivery_fee=fee, total=subtotal + fee,
                )
                Order.objects.filter(pk=order.pk).update(created_at=created)
                for v, q in lines:
                    OrderItem.objects.create(
                        order=order, variant=v, product_name=v.product.name, variant_name=v.name,
                        unit_price=v.price, quantity=q, line_total=v.price * q,
                    )
                steps = [S.NEW]
                if final == S.CANCELLED:
                    steps.append(S.CANCELLED)
                else:
                    steps = CHAIN[: CHAIN.index(final) + 1]
                prev = ""
                for k, st in enumerate(steps):
                    when = min(created + timedelta(minutes=20 * k), now)
                    h = OrderStatusHistory.objects.create(order=order, old_status=prev, new_status=st)
                    OrderStatusHistory.objects.filter(pk=h.pk).update(created_at=when)
                    prev = st
            self.stdout.write(f"Created {opts['count']} demo orders. Remove with: manage.py seed_demo_orders --clear")
