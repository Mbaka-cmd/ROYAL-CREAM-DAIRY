from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import never_cache

from apps.accounts.roles import has_dashboard_access


def staff_view(*perms):
    """Login + dashboard role + specific permissions, checked on the server for every request."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
            if not has_dashboard_access(request.user):
                raise PermissionDenied
            for perm in perms:
                if not request.user.has_perm(perm):
                    raise PermissionDenied
            return view(request, *args, **kwargs)

        return never_cache(wrapper)

    return decorator