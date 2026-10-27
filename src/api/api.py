from django.http import Http404
from ninja import NinjaAPI
from ninja.errors import ValidationError

from . import nodes, trees
from .conventions import APIError, bad_parameter, error_response, not_found

api = NinjaAPI(title="labeltree-db", version="1")


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


@api.get("/health")
def health(request):
    return {"status": "ok"}


api.add_router("/nodes", nodes.router)
api.add_router("/trees", trees.router)
