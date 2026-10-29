from django.http import Http404
from django.views.decorators.csp import csp_override
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError

from accounts.roles import Forbidden, NotAuthenticated

from . import changesets, nodes, orgs, trees, users, worms
from .auth import DEFAULT_AUTH
from .conventions import APIError, bad_parameter, error_response, not_found

# Every route needs a login unless it opts out with auth=None (see api.auth).
# The docs page loads Swagger UI from a CDN, which the site's CSP would block.
api = NinjaAPI(
    title="labeltree-db", version="1", auth=DEFAULT_AUTH, docs_decorator=csp_override({})
)


@api.exception_handler(APIError)
def handle_api_error(request, exc: APIError):
    return error_response(exc)


@api.exception_handler(ValidationError)
def handle_validation_error(request, exc: ValidationError):
    problems = "; ".join(
        f"{'.'.join(str(p) for p in e.get('loc', [])[1:]) or 'request'}: {e.get('msg')}"
        for e in exc.errors
    )
    return error_response(bad_parameter(problems or "Invalid parameter."))


@api.exception_handler(Http404)
def handle_404(request, exc):
    return error_response(not_found(str(exc) or "Not found."))


@api.exception_handler(AuthenticationError)
@api.exception_handler(NotAuthenticated)
def handle_unauthenticated(request, exc):
    return error_response(APIError(401, "unauthorized", "Log in or send an API token."))


@api.exception_handler(Forbidden)
def handle_forbidden(request, exc: Forbidden):
    return error_response(APIError(403, "forbidden", str(exc)))


@api.exception_handler(HttpError)
def handle_http_error(request, exc: HttpError):
    error = "forbidden" if exc.status_code == 403 else "error"
    return error_response(APIError(exc.status_code, error, exc.message))


@api.get("/health", auth=None)
def health(request):
    return {"status": "ok"}


api.add_router("/nodes", nodes.router)
api.add_router("/trees", trees.router)
api.add_router("/orgs", orgs.router)
api.add_router("/users", users.router)
api.add_router("/worms", worms.router)
api.add_router("", changesets.router)
