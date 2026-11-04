from django.core.management.base import BaseCommand, CommandError

from apps.customers import privacy
from apps.customers.models import Customer
from apps.customers.services import InvalidPhone, normalize_ke_phone


class Command(BaseCommand):
    help = "Remove one customer's personal details (data-subject deletion request)."

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True)
        parser.add_argument("--yes", action="store_true", help="Confirm the permanent removal")

    def handle(self, *args, **options):
        try:
            phone = normalize_ke_phone(options["phone"])
        except InvalidPhone as exc:
            raise CommandError(str(exc))
        customer = Customer.objects.filter(phone=phone).first()
        if customer is None:
            raise CommandError("No customer with that phone number.")
        if not options["yes"]:
            raise CommandError("This permanently removes the customer's personal details. Re-run with --yes to confirm.")
        try:
            done = privacy.anonymize_customer(customer)
        except privacy.OpenOrdersError:
            raise CommandError("This customer has open orders. Complete or cancel them first.")
        self.stdout.write("Anonymised." if done else "Already anonymised.")