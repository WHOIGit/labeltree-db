"""User accounts (spec: access-control "Creating a user account").

Site admins create accounts, for instance in the setup wizard. A new user is
in no organization; owners give them roles. Passwords are checked against the
site's password rules and are never echoed back.
"""

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from ninja import Router, Schema

from accounts.roles import require_superuser

from .conventions import APIError, bad_parameter, respond

router = Router(tags=["users"])


class NewUserIn(Schema):
    username: str
    password: str


@router.post("")
def create_user(request, body: NewUserIn):
    """Create a user account with a password (site admins only)."""
    require_superuser(request.user)
    User = get_user_model()
    field = User._meta.get_field(User.USERNAME_FIELD)
    username = body.username.strip()
    if not username:
        raise bad_parameter("username is required.")
    try:
        field.run_validators(username)
    except ValidationError as exc:
        raise bad_parameter(f"username: {' '.join(exc.messages)}") from None
    user = User(username=username)
    try:
        password_validation.validate_password(body.password, user=user)
    except ValidationError as exc:
        raise bad_parameter(f"password: {' '.join(exc.messages)}") from None
    user.set_password(body.password)
    try:
        with transaction.atomic():
            user.save(force_insert=True)
    except IntegrityError:
        raise APIError(409, "user_exists", f"User {username} already exists.") from None
    response = respond(request, {"username": user.get_username()})
    response.status_code = 201
    return response
