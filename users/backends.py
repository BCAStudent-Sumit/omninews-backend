from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

UserModel = get_user_model()


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Custom authentication backend that allows users to sign in with either
    their username or their email address (case-insensitive).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD) or kwargs.get('email')

        if not username or not password:
            return None

        username_str = str(username).strip()

        # Query by case-insensitive username or email
        user = UserModel.objects.filter(
            Q(username__iexact=username_str) | Q(email__iexact=username_str)
        ).first()

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
