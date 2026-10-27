from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Project user model.

    Identical to Django's default for now. Defining it from the start means
    fields can be added later without swapping AUTH_USER_MODEL mid-project.
    """
