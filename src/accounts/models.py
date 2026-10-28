import hashlib
import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """Project user model.

    Identical to Django's default for now. Defining it from the start means
    fields can be added later without swapping AUTH_USER_MODEL mid-project.
    """


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> tuple[str, str]:
    """(key, hash) for a new token."""
    key = secrets.token_urlsafe(32)
    return key, hash_key(key)


class ApiToken(models.Model):
    """A script's credential, sent as `Authorization: Token <key>`.

    Only the key's hash is stored; the key itself is shown once, when the token
    is created. A token acts as its user, with that user's roles.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens"
    )
    name = models.CharField(max_length=100, help_text="What the token is for, e.g. the script.")
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user} / {self.name}"

    @classmethod
    def issue(cls, user, name: str) -> tuple[ApiToken, str]:
        """Create a token. Returns (token, key); the key can't be recovered later."""
        key, key_hash = new_key()
        return cls.objects.create(user=user, name=name, key_hash=key_hash), key

    @classmethod
    def lookup(cls, key: str) -> ApiToken | None:
        """The live token for a key, or None if unknown or revoked."""
        return (
            cls.objects.select_related("user")
            .filter(key_hash=hash_key(key), revoked_at__isnull=True, user__is_active=True)
            .first()
        )


class Organization(models.Model):
    """A group that maintains trees. Every tree belongs to one; roles are held here."""

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class Role(models.IntegerChoices):
    """A user's role in an organization, on all its trees. Each role includes
    every role below it."""

    READER = 1, "reader"
    DRAFTER = 2, "drafter"
    APPROVER = 3, "approver"
    OWNER = 4, "owner"

    @classmethod
    def named(cls, name: str) -> Role:
        for role in cls:
            if role.label == name:
                return role
        raise ValueError(name)


class OrgMember(models.Model):
    """One row per user and organization, holding the user's highest role in it."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_roles"
    )
    org = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="members")
    role = models.PositiveSmallIntegerField(choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "org"], name="orgmember_user_org_uniq"),
        ]
        ordering = ["org", "-role", "user__username"]

    def __str__(self):
        return f"{self.user} {Role(self.role).label} in {self.org_id}"
