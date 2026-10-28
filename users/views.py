"""
users/views.py — Authentication & profile views for OmniNews.

Security notes
--------------
* FIX 5: UserProfileView.get_object() no longer auto-promotes any username
  (e.g. 'sumit', 'admin') to superuser on every profile load.  Privilege
  escalation must be done deliberately via `manage.py shell` or the Django
  admin backend.  The old code let an attacker register that username and
  immediately gain superuser rights.

* FIX 4: PasswordResetView now uses Django's built-in PasswordResetTokenGenerator
  for a signed, single-use, time-limited token (default 3-day validity).
  Flow:
    POST /api/auth/password-reset/         { "email": "..." }
      → looks up user, emails a signed token link; always returns 200 so
        attackers cannot enumerate valid emails.
    POST /api/auth/password-reset/confirm/ { "uid": "...", "token": "...", "new_password": "..." }
      → verifies uid + token, sets password, invalidates token.
  The old unauthenticated endpoint that took only a username/email and a new
  password allowed any visitor to take over any account, including admin.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.conf import settings

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RegisterSerializer, UserProfileSerializer

User = get_user_model()

_token_generator = PasswordResetTokenGenerator()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class RegisterView(generics.CreateAPIView):
    """Register a new OmniNews account."""
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = (permissions.AllowAny,)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class UserProfileView(generics.RetrieveUpdateAPIView):
    """Retrieve or update the authenticated user's profile."""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # FIX 5: simply return the authenticated user — no privilege escalation.
        return self.request.user


# ---------------------------------------------------------------------------
# Password Reset — step 1: request
# ---------------------------------------------------------------------------

class PasswordResetRequestView(APIView):
    """
    POST { "email": "user@example.com" }

    Sends a password-reset email containing a signed uid + token link.
    Always returns HTTP 200 regardless of whether the email is registered
    (prevents email enumeration by attackers).
    """
    permission_classes = [permissions.AllowAny]
    # Rate-limited by global anon throttle (60/min); add a named scope if needed.

    _SUCCESS_MSG = (
        "If an account with that email exists, a password-reset link has been "
        "sent. Check your inbox (and spam folder)."
    )

    def post(self, request):
        email = str(request.data.get('email', '')).strip().lower()

        if not email:
            return Response(
                {"error": "Email address is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Look up silently — do not reveal whether the email is registered.
        user = User.objects.filter(email__iexact=email).first()

        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = _token_generator.make_token(user)

            # Build the reset link pointing at the Flutter/Vercel frontend
            frontend_url = getattr(settings, 'FRONTEND_URL', 'https://omninewsproject.vercel.app')
            reset_link = f"{frontend_url}/password-reset/confirm?uid={uid}&token={token}"

            send_mail(
                subject="OmniNews — Reset your password",
                message=(
                    f"Hi {user.username},\n\n"
                    f"Someone (hopefully you) requested a password reset for your OmniNews account.\n\n"
                    f"Click the link below to set a new password. "
                    f"This link expires in 3 days and can only be used once.\n\n"
                    f"{reset_link}\n\n"
                    f"If you did not request this, you can safely ignore this email.\n\n"
                    f"— The OmniNews Team"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,  # Do not 500 if SMTP is misconfigured
            )

        # Always 200 — do not reveal whether the email was found
        return Response({"detail": self._SUCCESS_MSG}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Password Reset — step 2: confirm
# ---------------------------------------------------------------------------

class PasswordResetConfirmView(APIView):
    """
    POST { "uid": "<base64>", "token": "<signed-token>", "new_password": "..." }

    Verifies the signed token, sets the new password, and invalidates the token
    (Django's PasswordResetTokenGenerator includes last_login in the hash, so
    the token becomes invalid the next time the user logs in or the token is used).
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        uid_b64 = str(request.data.get('uid', '')).strip()
        token = str(request.data.get('token', '')).strip()
        new_password = str(request.data.get('new_password', ''))

        # --- Basic input validation ---
        if not uid_b64 or not token:
            return Response(
                {"error": "uid and token are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(new_password) < 8:
            return Response(
                {"error": "New password must be at least 8 characters long."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Decode uid ---
        try:
            uid = force_str(urlsafe_base64_decode(uid_b64))
            user = User.objects.get(pk=uid)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return Response(
                {"error": "Password reset link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Verify token ---
        if not _token_generator.check_token(user, token):
            return Response(
                {"error": "Password reset link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Set new password (Django's set_password hashes it) ---
        user.set_password(new_password)
        user.save()

        return Response(
            {"detail": "Your password has been reset successfully. You may now sign in."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Backward-compat alias — keep old PasswordResetView name importable
# (users/urls.py and any migration references won't break)
# ---------------------------------------------------------------------------
PasswordResetView = PasswordResetRequestView
