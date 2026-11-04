from django.urls import path

from . import views

urlpatterns = [
    path("api/cart/validate/", views.cart_validate, name="cart_validate"),
    path("checkout/", views.checkout, name="checkout"),
    path("order/<str:token>/", views.order_confirmation, name="order_confirmation"),
]