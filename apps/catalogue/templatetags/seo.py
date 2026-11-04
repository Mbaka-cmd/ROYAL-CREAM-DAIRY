import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_ESCAPES = {ord(">"): "\\u003E", ord("<"): "\\u003C", ord("&"): "\\u0026"}


@register.simple_tag
def jsonld(data):
    """Render a JSON-LD block. <, > and & are escaped so data can never close the script tag."""
    if not data:
        return ""
    payload = json.dumps(data, ensure_ascii=True).translate(_ESCAPES)
    return mark_safe('<script type="application/ld+json">' + payload + "</script>")