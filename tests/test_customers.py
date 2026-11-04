from django.test import TestCase

from apps.customers.models import Customer
from apps.customers.services import InvalidPhone, normalize_ke_phone, upsert_customer


class PhoneTests(TestCase):
    def test_valid_formats(self):
        cases = {
            "0712 345 678": "+254712345678",
            "+254712345678": "+254712345678",
            "254712345678": "+254712345678",
            "712345678": "+254712345678",
            "0112345678": "+254112345678",
            "07-12-345-678": "+254712345678",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_ke_phone(raw), expected)

    def test_invalid_formats(self):
        for raw in ["", None, "12345", "abc", "0812345678", "+2547123456789", "07123"]:
            with self.subTest(raw=raw):
                with self.assertRaises(InvalidPhone):
                    normalize_ke_phone(raw)


class UpsertCustomerTests(TestCase):
    def test_creates_with_consent(self):
        c = upsert_customer(name="Jane", phone="0712345678", whatsapp_consent=True)
        self.assertEqual(c.phone, "+254712345678")
        self.assertTrue(c.whatsapp_opt_in)
        self.assertIsNotNone(c.whatsapp_consent_at)

    def test_reuses_customer_by_phone_and_updates_name(self):
        upsert_customer(name="Jane", phone="0712345678", whatsapp_consent=True)
        upsert_customer(name="Jane W", phone="+254712345678", whatsapp_consent=True)
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(Customer.objects.get().name, "Jane W")

    def test_withdrawing_consent_clears_it(self):
        upsert_customer(name="Jane", phone="0712345678", whatsapp_consent=True)
        c = upsert_customer(name="Jane", phone="0712345678", whatsapp_consent=False)
        self.assertFalse(c.whatsapp_opt_in)
        self.assertIsNone(c.whatsapp_consent_at)