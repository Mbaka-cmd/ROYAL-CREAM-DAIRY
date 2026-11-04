import logging

from django.conf import settings
from django.contrib.auth.views import LoginView, LogoutView
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit

from .forms import OwnerAuthenticationForm

logger = logging.getLogger(__name__)


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

    def post(self, request, *args, **kwargs):
        if getattr(request, "limited", False):
            logger.warning("Login rate limit hit from %s", request.META.get("REMOTE_ADDR", "?"))
            form = self.get_form()
            form.add_error(None, "Too many login attempts. Please wait 15 minutes and try again.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)


owner_logout = LogoutView.as_view(next_page="owner_login")