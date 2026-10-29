from django.urls import path
from .views import (
    PlanListView,
    SubscriptionMeView,
    RevenueCatWebhookView,
    SubscriptionSyncView,
    StreamTokenView,
    VrPairView,
    VrPairRedeemView,
)

urlpatterns = [
    path('plans/', PlanListView.as_view(), name='subscription_plans'),
    path('me/', SubscriptionMeView.as_view(), name='subscription_me'),
    path('webhook/revenuecat/', RevenueCatWebhookView.as_view(), name='revenuecat_webhook'),
    path('sync/', SubscriptionSyncView.as_view(), name='subscription_sync'),
    path('stream-token/', StreamTokenView.as_view(), name='stream_token'),
    path('vr-pair/', VrPairView.as_view(), name='vr_pair'),
    path('vr-pair/redeem/', VrPairRedeemView.as_view(), name='vr_pair_redeem'),
]
