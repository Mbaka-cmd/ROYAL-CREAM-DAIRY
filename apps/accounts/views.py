import logging
import os

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpResponseRedirect
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit

from .forms import OwnerAuthenticationForm
from .roles import ROLE_OWNER, ensure_roles

logger = logging.getLogger(__name__)

DEMO_USERNAME = "demo_owner"


def demo_login_enabled():
    # Only ever on in DEBUG, and only when DEMO_OPEN_LOGIN=1 is set in .env
    return bool(settings.DEBUG) and os.environ.get("DEMO_OPEN_LOGIN", "0").strip() == "1"


def _ip_rate(group, request):
    return settings.LOGIN_RATE_LIMIT


def _user_rate(group, request):
    return settings.LOGIN_USER_RATE_LIMIT


@method_decorator(ratelimit(key="ip", rate=_ip_rate, method="POST", block=False), name="dispatch")
@method_decorator(ratelimit(key="post:username", rate=_user_rate, method="POST", block=False), name="dispatch")
class OwnerLoginView(LoginView):
    template_name = "dashboard/login.html"
    authentication_form = OwnerAuthenticationForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["demo_login_enabled"] = demo_login_enabled()
        return ctx

    def post(self, request, *args, **kwargs):
        if getattr(request, "limited", False):
            logger.warning("Login rate limit hit from %s", request.META.get("REMOTE_ADDR", "?"))
            form = self.get_form()
            form.add_error(None, "Too many login attempts. Please wait 15 minutes and try again.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        if demo_login_enabled() and "demo_login" in request.POST:
            ensure_roles()
            User = get_user_model()
            user, created = User.objects.get_or_create(username=DEMO_USERNAME, defaults={"is_staff": True})
            if created:
                user.set_unusable_password()
            user.first_name = "Adalyn"
            user.save()
            user.groups.add(Group.objects.get(name=ROLE_OWNER))
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            logger.warning("Demo owner login used from %s", request.META.get("REMOTE_ADDR", "?"))
            return HttpResponseRedirect(self.get_success_url())
        return super().post(request, *args, **kwargs)


owner_logout = LogoutView.as_view(next_page="owner_login")
