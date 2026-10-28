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
        # SECURITY FIX: removed auto-promotion of 'sumit'/'admin' usernames to superuser.
        # Privilege escalation must only happen via the Django admin shell or management command.
        # The old code let any attacker register as 'sumit' or 'admin' and gain superuser rights.
        return user


class PasswordResetView(APIView):
    """
    Allows a logged-in user to change their own password.
    Unauthenticated password-reset (by username/email alone) is disabled —
    it allowed any visitor to take over any account with no email verification.
    If you need a password-reset flow, implement proper email token delivery
    (e.g. django.contrib.auth.views.PasswordResetView with email backend).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        current_password = str(request.data.get('current_password', ''))
        new_password = str(request.data.get('new_password', ''))

        if not current_password:
            return Response(
                {"error": "Please provide your current password."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not user.check_password(current_password):
            return Response(
                {"error": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(new_password) < 8:
            return Response(
                {"error": "New password must be at least 8 characters long."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if current_password == new_password:
            return Response(
                {"error": "New password must be different from your current password."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(new_password)
        user.save()

        return Response(
            {"detail": "Your password has been successfully changed. Please sign in again."},
            status=status.HTTP_200_OK
        )
