import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


@never_cache
@require_safe
def healthz(request):
    """Uptime-monitor endpoint: confirms the app is up and can reach its database. No details are exposed."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("Health check: database unreachable")
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})