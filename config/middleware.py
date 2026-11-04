from django.conf import settings

from .ga import valid_ga_id

ADMIN_PREFIX = "/django-admin/"

# Hosts required by Google Analytics 4 (per Google's CSP guide for the tag platform).
GA_SCRIPT = "https://*.googletagmanager.com"
GA_CONNECT = "https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com"
GA_IMG = "https://*.google-analytics.com https://*.googletagmanager.com"

PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


def build_csp(path):
    if path.startswith(ADMIN_PREFIX):
        # Django's admin uses inline scripts/styles. The relaxation applies to the admin only.
        parts = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
        ]
    else:
        ga = valid_ga_id(getattr(settings, "GA_MEASUREMENT_ID", ""))
        parts = [
            "default-src 'self'",
            "script-src 'self'" + (f" {GA_SCRIPT}" if ga else ""),
            "style-src 'self'",
            "img-src 'self' data:" + (f" {GA_IMG}" if ga else ""),
            "font-src 'self'",
            "connect-src 'self'" + (f" {GA_CONNECT}" if ga else ""),
            "manifest-src 'self'",
        ]
    parts += ["base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'", "object-src 'none'"]
    if not settings.DEBUG:
        parts.append("upgrade-insecure-requests")
    return "; ".join(parts)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not response.has_header("Content-Security-Policy"):
            response["Content-Security-Policy"] = build_csp(request.path)
        if not response.has_header("Permissions-Policy"):
            response["Permissions-Policy"] = PERMISSIONS_POLICY
        return response