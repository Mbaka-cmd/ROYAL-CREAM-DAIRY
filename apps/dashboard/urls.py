from django.urls import path

from apps.accounts import views as account_views

from . import views

urlpatterns = [
    path("login/", account_views.OwnerLoginView.as_view(), name="owner_login"),
    path("logout/", account_views.owner_logout, name="owner_logout"),
    path("", views.home, name="owner_home"),
    path("search/", views.search, name="owner_search"),
    path("alerts/", views.alerts, name="owner_alerts"),
    path("orders/", views.order_list, name="owner_orders"),
    path("orders/<int:pk>/", views.order_detail, name="owner_order_detail"),
    path("orders/<int:pk>/status/", views.order_status, name="owner_order_status"),
    path("inventory/", views.inventory_list, name="owner_inventory"),
    path("inventory/adjust/", views.inventory_adjust, name="owner_inventory_adjust"),
    path("products/", views.product_list, name="owner_products"),
    path("products/new/", views.product_create, name="owner_product_create"),
    path("products/<int:pk>/update/", views.product_update, name="owner_product_update"),
    path("notifications/", views.notification_list, name="owner_notifications"),
    path("notifications/<int:pk>/retry/", views.notification_retry, name="owner_notification_retry"),
    path("reports/", views.reports, name="owner_reports"),
]