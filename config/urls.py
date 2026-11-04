import re

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from . import health, media

urlpatterns = [
    path("healthz/", health.healthz, name="healthz"),
    path("django-admin/", admin.site.urls),
    path("owner/", include("apps.dashboard.urls")),
    path("", include("apps.catalogue.urls")),
    path("", include("apps.orders.urls")),
    path("", include("apps.notifications.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.SERVE_MEDIA:
    _prefix = re.escape(settings.MEDIA_URL.strip("/"))
    urlpatterns += [re_path(rf"^{_prefix}/(?P<path>.*)$", media.serve_media, name="media")]