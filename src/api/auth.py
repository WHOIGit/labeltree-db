"""API authentication (spec: access-control).

Token and session auth are the API's default; read routes opt out with
`auth=None` and are listed in ANONYMOUS_ROUTES, which a test checks against
every route, so a new route needs a login unless it is deliberately listed.
"""

from django.utils import timezone
from ninja.errors import HttpError
from ninja.security import APIKeyHeader
from ninja.security.apikey import APIKeyCookie
from ninja.utils import check_csrf

from accounts.models import ApiToken


class TokenAuth(APIKeyHeader):
    """`Authorization: Token <key>`; not CSRF-checked."""

    param_name = "Authorization"

    def authenticate(self, request, key):
        if not key or not key.startswith("Token "):
            return None
        token = ApiToken.lookup(key.removeprefix("Token ").strip())
        if token is None:
            return None
        ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        request.user = token.user  # roles and recorded usernames read request.user
        return token.user


class SessionAuth(APIKeyCookie):
    """The web app's Django session, CSRF-checked.

    Unlike ninja's SessionAuth, an anonymous request gets 401 rather than a CSRF
    failure, since there is no session to protect.
    """

    def __init__(self):
        from django.conf import settings

        self.param_name = settings.SESSION_COOKIE_NAME
        super().__init__(csrf=True)

    def _get_key(self, request):
        if not request.user.is_authenticated:
            return None
        if not getattr(request, "_ninja_csrf_exempt", False) and check_csrf(request):
            raise HttpError(403, "CSRF check failed.")
        return request.COOKIES.get(self.param_name)

    def authenticate(self, request, key):
        return request.user if request.user.is_authenticated else None


DEFAULT_AUTH = [TokenAuth(), SessionAuth()]
