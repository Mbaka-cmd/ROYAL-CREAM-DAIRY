import os

from django.conf import settings
from django.core.checks import Warning, register


@register()
def privacy_contact_configured(app_configs, **kwargs):
    """Production only: the privacy policy needs a way for people to reach the business."""
    if settings.DEBUG or not os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith("production"):
        return []
    if settings.PRIVACY_CONTACT_EMAIL:
        return []
    return [
        Warning(
            "PRIVACY_CONTACT_EMAIL is not set; the privacy policy has no contact for data requests.",
            hint="Set PRIVACY_CONTACT_EMAIL in the production .env before launch.",
            id="royalcream.W001",
        )
    ]