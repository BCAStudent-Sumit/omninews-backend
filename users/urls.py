from django.urls import path
from .views import (
    RegisterView,
    UserProfileView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    # Step 1: send reset email
    path('password-reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    # Step 2: verify token + set new password
    path('password-reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('me/', UserProfileView.as_view(), name='user-me'),
    path('profile/', UserProfileView.as_view(), name='user-profile'),
]
