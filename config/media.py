from django.conf import settings
from django.views.decorators.cache import cache_control
from django.views.static import serve


@cache_control(public=True, max_age=86400)
def serve_media(request, path):
    """Serve uploaded product images. Path traversal and directory listings are refused by Django's serve()."""
    return serve(request, path, document_root=settings.MEDIA_ROOT)