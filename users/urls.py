from django.urls import path
from .views import RegisterView, UserProfileView, PasswordResetView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('password-reset/', PasswordResetView.as_view(), name='password-reset'),
    path('me/', UserProfileView.as_view(), name='user-me'),
    path('profile/', UserProfileView.as_view(), name='user-profile'),
]