"""
URL configuration for omninews_backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, re_path, include
from django.http import JsonResponse
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from drf_spectacular.views import (  # type: ignore
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

def api_root_view(request):
    return JsonResponse({
        "status": "online",
        "service": "OmniNews Cloud Backend",
        "version": "1.0.0",
        "endpoints": {
            "feed": "/api/news/feed/",
            "docs": "/api/docs/",
            "login": "/api/auth/login/",
            "register": "/api/auth/register/",
            "admin": "/admin/"
        },
        "website": "https://omninews-taupe.vercel.app"
    })

urlpatterns = [
    path('', api_root_view, name='root'),
    re_path(r'^api/?$', api_root_view, name='api_root'),
    path('admin/', admin.site.urls),
    path('api/podcasts/', include('news.urls')),
    path('api/news/', include('news.urls')),
    path('api/subscriptions/', include('subscriptions.urls')),

    # JWT Auth Endpoints
    path('api/auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Registration endpoint
    path('api/auth/', include('users.urls')),

    # OpenAPI Schema & Interactive Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
