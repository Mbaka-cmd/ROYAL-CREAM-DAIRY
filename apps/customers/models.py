from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=16, unique=True)
    whatsapp_opt_in = models.BooleanField(default=False)
    whatsapp_consent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.phone})"