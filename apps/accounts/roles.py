import logging

from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Group, Permission
from django.db import DEFAULT_DB_ALIAS
from django.db.models import Q

logger = logging.getLogger(__name__)

ROLE_OWNER = "Owner"
ROLE_ORDER_MANAGER = "Order Manager"
ROLE_INVENTORY_MANAGER = "Inventory Manager"
ROLE_NAMES = (ROLE_OWNER, ROLE_ORDER_MANAGER, ROLE_INVENTORY_MANAGER)

BUSINESS_APPS = ("catalogue", "customers", "inventory", "orders", "delivery", "notifications")

ORDER_MANAGER_PERMISSIONS = (
    "orders.view_order",
    "orders.change_order",
    "orders.view_orderitem",
    "orders.view_orderstatushistory",
    "customers.view_customer",
    "notifications.view_notification",
    "notifications.change_notification",
    "inventory.view_inventory",
    "catalogue.view_category",
    "catalogue.view_product",
    "catalogue.view_productvariant",
)

INVENTORY_MANAGER_PERMISSIONS = (
    "inventory.view_inventory",
    "inventory.change_inventory",
    "inventory.view_stockmovement",
    "catalogue.view_category",
    "catalogue.view_product",
    "catalogue.add_product",
    "catalogue.change_product",
    "catalogue.view_productvariant",
    "catalogue.add_productvariant",
    "catalogue.change_productvariant",
)


def has_dashboard_access(user):
    """Signed in, active, and either a superuser or in one of the dashboard roles."""
    if not (user.is_authenticated and user.is_active):
        return False
    return user.is_superuser or user.groups.filter(name__in=ROLE_NAMES).exists()


def _resolve(specs, using):
    query = Q()
    for spec in specs:
        app_label, codename = spec.split(".")
        query |= Q(content_type__app_label=app_label, codename=codename)
    found = list(Permission.objects.using(using).filter(query))
    if len(found) != len(set(specs)):
        logger.warning("Role setup: %s permission(s) not found", len(set(specs)) - len(found))
    return found


def ensure_roles(using=DEFAULT_DB_ALIAS):
    """Create the role groups and give them their permissions. Additive and idempotent:
    permissions added manually in the admin are never removed."""
    for label in BUSINESS_APPS:
        try:
            config = django_apps.get_app_config(label)
        except LookupError:
            continue
        create_permissions(config, verbosity=0, using=using)

    owner, _ = Group.objects.using(using).get_or_create(name=ROLE_OWNER)
    owner.permissions.add(*Permission.objects.using(using).filter(content_type__app_label__in=BUSINESS_APPS))

    order_manager, _ = Group.objects.using(using).get_or_create(name=ROLE_ORDER_MANAGER)
    order_manager.permissions.add(*_resolve(ORDER_MANAGER_PERMISSIONS, using))

    inventory_manager, _ = Group.objects.using(using).get_or_create(name=ROLE_INVENTORY_MANAGER)
    inventory_manager.permissions.add(*_resolve(INVENTORY_MANAGER_PERMISSIONS, using))