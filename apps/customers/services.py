import re

from django.utils import timezone

from .models import Customer


class InvalidPhone(ValueError):
    pass


def normalize_ke_phone(raw):
    """Return +254XXXXXXXXX for Kenyan mobile numbers (07.., 01.., 7.., 254.., +254..)."""
    digits = re.sub(r"[\s\-().]", "", str(raw or ""))
    if digits.startswith("+"):
        digits = digits[1:]
    if not digits.isdigit():
        raise InvalidPhone("Enter a valid Kenyan phone number.")
    if digits.startswith("254"):
        national = digits[3:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits
    if not re.fullmatch(r"[17]\d{8}", national):
        raise InvalidPhone("Enter a valid Kenyan phone number.")
    return "+254" + national


def upsert_customer(*, name, phone, whatsapp_consent):
    """Latest checkout choice wins for WhatsApp consent; consent time is set when it turns on."""
    phone = normalize_ke_phone(phone)
    consent = bool(whatsapp_consent)
    customer, created = Customer.objects.get_or_create(
        phone=phone,
        defaults={
            "name": name,
            "whatsapp_opt_in": consent,
            "whatsapp_consent_at": timezone.now() if consent else None,
        },
    )
    if created:
        return customer
    fields = []
    if customer.name != name:
        customer.name = name
        fields.append("name")
    if consent != customer.whatsapp_opt_in:
        customer.whatsapp_opt_in = consent
        customer.whatsapp_consent_at = timezone.now() if consent else None
        fields += ["whatsapp_opt_in", "whatsapp_consent_at"]
    if fields:
        customer.save(update_fields=fields + ["updated_at"])
    return customer