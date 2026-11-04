from django.conf import settings
from django.utils.html import strip_tags


def site_base_url(request):
    configured = (settings.SITE_URL or "").strip().rstrip("/")
    if configured:
        return configured
    return f"{request.scheme}://{request.get_host()}"


def safe_https_url(value):
    value = (value or "").strip()
    return value if value.startswith("https://") and " " not in value else ""


def organization_jsonld(request):
    base = site_base_url(request)
    org = {
        "@type": "Organization",
        "@id": base + "/#organization",
        "name": settings.SITE_NAME,
        "url": base + "/",
        "slogan": "Pure Goodness, Every Day.",
        "areaServed": {"@type": "Place", "name": "Chuka, Kenya"},
    }
    same_as = [u for u in (safe_https_url(settings.SOCIAL_FACEBOOK_URL), safe_https_url(settings.SOCIAL_TIKTOK_URL)) if u]
    if same_as:
        org["sameAs"] = same_as
    site = {
        "@type": "WebSite",
        "@id": base + "/#website",
        "name": settings.SITE_NAME,
        "url": base + "/",
        "publisher": {"@id": base + "/#organization"},
    }
    return {"@context": "https://schema.org", "@graph": [org, site]}


def product_description(product):
    text = " ".join(strip_tags(product.description or "").split())
    if text:
        return text[:152] + "..." if len(text) > 155 else text
    return f"Order {product.name} from Royal Cream Dairy for delivery around Chuka. Pay on delivery."


def product_jsonld(product, request, url):
    base = site_base_url(request)
    offers = [
        {
            "@type": "Offer",
            "name": variant.name,
            "price": f"{variant.price:.2f}",
            "priceCurrency": "KES",
            "availability": "https://schema.org/InStock" if variant.available > 0 else "https://schema.org/OutOfStock",
            "url": url,
        }
        for variant in product.variants.all()
    ]
    data = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.name,
        "category": product.category.name,
        "offers": offers,
    }
    description = " ".join(strip_tags(product.description or "").split())
    if description:
        data["description"] = description[:300]
    if product.image:
        data["image"] = [base + product.image.url]
    return data


def ga_item_data(product):
    items = [
        {
            "item_id": str(variant.id),
            "item_name": f"{product.name} {variant.name}",
            "item_category": product.category.name,
            "price": float(variant.price),
            "quantity": 1,
        }
        for variant in product.variants.all()
    ]
    return {"currency": "KES", "value": items[0]["price"] if items else 0, "items": items}