from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .roles import has_dashboard_access


class OwnerAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not has_dashboard_access(user):
            raise forms.ValidationError("This account does not have dashboard access.", code="no_access")