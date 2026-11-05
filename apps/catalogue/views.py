from urllib.parse import urlencode
from xml.sax.saxutils import escape

from django.conf import settings
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_safe

from . import seo
from .models import Category, Product
from .selectors import storefront_products


def home(request):
    products = list(storefront_products()[:6])
    return render(
        request,
        "storefront/home.html",
        {
            "products": products,
            "categories": list(Category.objects.filter(is_active=True)),
            "organization_jsonld": seo.organization_jsonld(request),
        },
    )


def product_list(request):
    slug = request.GET.get("category", "").strip()
    page = Paginator(storefront_products(slug or None), 12).get_page(request.GET.get("page"))
    categories = list(Category.objects.filter(is_active=True))
    params = {}
    if slug:
        params["category"] = slug
    if page.number > 1:
        params["page"] = page.number
    canonical = seo.site_base_url(request) + request.path + ("?" + urlencode(params) if params else "")
    return render(
        request,
        "catalogue/product_list.html",
        {
            "page": page,
            "categories": categories,
            "active_category": slug,
            "active_category_name": next((c.name for c in categories if c.slug == slug), ""),
            "canonical_url": canonical,
        },
    )


def product_detail(request, slug):
    product = get_object_or_404(storefront_products(), slug=slug)
    base = seo.site_base_url(request)
    url = base + request.path
    context = {
        "product": product,
        "canonical_url": url,
        "meta_description": seo.product_description(product),
        "product_jsonld": seo.product_jsonld(product, request, url),
        "ga_view_item": seo.ga_item_data(product),
    }
    if product.image:
        context["og_image"] = base + product.image.url
    return render(request, "catalogue/product_detail.html", context)


def privacy(request):
    return render(
        request,
        "storefront/privacy.html",
        {
            "retention_months": settings.PERSONAL_DATA_RETENTION_MONTHS,
            "contact_email": settings.PRIVACY_CONTACT_EMAIL,
        },
    )


@require_safe
def robots_txt(request):
    base = seo.site_base_url(request)
    lines = [
        "User-agent: *",
        "Disallow: /owner/",
        "Disallow: /django-admin/",
        "Disallow: /checkout/",
        "Disallow: /order/",
        "Disallow: /api/",
        "Disallow: /webhooks/",
        "Disallow: /healthz/",
        "",
        f"Sitemap: {base}/sitemap.xml",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")


@require_safe
def sitemap_xml(request):
    base = seo.site_base_url(request)
    entries = [
        (base + reverse("home"), None),
        (base + reverse("product_list"), None),
        (base + reverse("privacy"), None),
    ]
    products = (
        Product.objects.filter(is_active=True, category__is_active=True, variants__is_active=True)
        .distinct()
        .order_by("slug")
        .values_list("slug", "updated_at")
    )
    for slug, updated_at in products:
        entries.append((base + reverse("product_detail", args=[slug]), updated_at.date().isoformat()))
    rows = []
    for loc, lastmod in entries:
        row = f"  <url><loc>{escape(loc)}</loc>"
        if lastmod:
            row += f"<lastmod>{lastmod}</lastmod>"
        rows.append(row + "</url>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(rows) + "\n</urlset>\n"
    )
    return HttpResponse(xml, content_type="application/xml")