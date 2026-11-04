import re
from urllib.parse import quote

from django.conf import settings
from django.templatetags.static import static

from apps.catalogue.seo import safe_https_url, site_base_url

from .ga import valid_ga_id


def site(request):
    base = site_base_url(request)
    digits = re.sub(r"\D", "", settings.PUBLIC_WHATSAPP_NUMBER or "")
    whatsapp_url = ""
    if 8 <= len(digits) <= 15:
        whatsapp_url = f"https://wa.me/{digits}?text={quote('Hello Royal Cream Dairy')}"
    og_default = (settings.DEFAULT_OG_IMAGE or "").strip()
    return {
        "SITE_NAME": settings.SITE_NAME,
        "site_url": base,
        "canonical_url": base + quote(request.path),
        "og_image": (base + static(og_default)) if og_default else "",
        "GA_ID": settings.GA_MEASUREMENT_ID if valid_ga_id(settings.GA_MEASUREMENT_ID) else "",
        "PUBLIC_WHATSAPP_URL": whatsapp_url,
        "SOCIAL_FACEBOOK_URL": safe_https_url(settings.SOCIAL_FACEBOOK_URL),
        "SOCIAL_TIKTOK_URL": safe_https_url(settings.SOCIAL_TIKTOK_URL),
        "GOOGLE_SITE_VERIFICATION": (settings.GOOGLE_SITE_VERIFICATION or "").strip(),
    }