from .models import DeliveryZone


def active_zones():
    return DeliveryZone.objects.filter(is_active=True)


def zone_by_id(zone_id):
    """Return the active zone for a client-supplied id, or None. Never raises on bad input."""
    try:
        zid = int(zone_id)
    except (TypeError, ValueError):
        return None
    return active_zones().filter(pk=zid).first()
