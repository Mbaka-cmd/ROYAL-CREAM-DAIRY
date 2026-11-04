from django.urls import path

from . import webhooks

urlpatterns = [
    path("webhooks/whatsapp/", webhooks.whatsapp_webhook, name="whatsapp_webhook"),
]