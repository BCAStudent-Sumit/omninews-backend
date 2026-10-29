from django.urls import path
from .views import (
    PlanListView,
    SubscriptionMeView,
    RevenueCatWebhookView,
    SubscriptionSyncView,
    StreamTokenView,
)

urlpatterns = [
    path('plans/', PlanListView.as_view(), name='subscription_plans'),
    path('me/', SubscriptionMeView.as_view(), name='subscription_me'),
    path('webhook/revenuecat/', RevenueCatWebhookView.as_view(), name='revenuecat_webhook'),
    path('sync/', SubscriptionSyncView.as_view(), name='subscription_sync'),
    path('stream-token/', StreamTokenView.as_view(), name='stream_token'),
]
