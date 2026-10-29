import os
import logging
import requests
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from .models import Plan, Subscription, PaymentEvent
from .serializers import PlanSerializer, UserSubscriptionStatusSerializer
from .providers.base import RevenueCatProvider
from .signing import StreamSigner

logger = logging.getLogger(__name__)
User = get_user_model()


class PlanListView(APIView):
    """
    GET /api/subscriptions/plans/
    Public listing of all available subscription plans with pricing in INR and feature bullet points.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses={200: PlanSerializer(many=True)})
    def get(self, request):
        plans = Plan.objects.filter(active=True).order_by('price_inr')
        serializer = PlanSerializer(plans, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SubscriptionMeView(APIView):
    """
    GET /api/subscriptions/me/
    Returns the authenticated user's active membership plan, status, period end date,
    and computed entitlements ({live_2d: bool, live_vr: bool}).
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: UserSubscriptionStatusSerializer})
    def get(self, request):
        sub = (
            Subscription.objects.filter(user=request.user)
            .select_related('plan')
            .order_by('-updated_at')
            .first()
        )

        has_sub = sub.is_currently_active if sub else False

        data = {
            "has_subscription": has_sub,
            "plan": PlanSerializer(sub.plan).data if (sub and sub.plan) else None,
            "status": sub.status if sub else None,
            "current_period_end": sub.current_period_end if sub else None,
            "entitlements": sub.entitlements if sub else {"live_2d": False, "live_vr": False},
        }
        return Response(data, status=status.HTTP_200_OK)


class RevenueCatWebhookView(APIView):
    """
    POST /api/subscriptions/webhook/revenuecat/
    Public webhook receiver for RevenueCat event streams.
    Enforces constant-time authorization verification and idempotent event ingestion.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        provider = RevenueCatProvider()

        # 1. Constant-time Authorization verification
        if not provider.verify_webhook(request):
            return Response(
                {"detail": "Invalid or missing webhook authorization credentials."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        payload = request.data if isinstance(request.data, dict) else {}
        app_user_id, plan_slug, sub_status, period_end, event_id = provider.parse_event(payload)

        if not event_id:
            event_id = f"rc_anon_{timezone.now().timestamp()}"

        # 2. Idempotency Check: Ignore duplicate event IDs
        if PaymentEvent.objects.filter(event_id=event_id).exists():
            logger.info(f"[RevenueCatWebhook] Duplicate event {event_id} ignored.")
            return Response(
                {"status": "duplicate_ignored", "event_id": event_id},
                status=status.HTTP_200_OK
            )

        # 3. Record event
        event_type = payload.get('event', {}).get('type', 'UNKNOWN')
        payment_event = PaymentEvent.objects.create(
            provider='revenuecat',
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            processed=False
        )

        # 4. Resolve Django User
        user = None
        if app_user_id:
            if app_user_id.isdigit():
                user = User.objects.filter(id=int(app_user_id)).first()
            if not user:
                user = User.objects.filter(username=app_user_id).first()
            if not user:
                user = User.objects.filter(email__iexact=app_user_id).first()

        if not user:
            logger.warning(f"[RevenueCatWebhook] Could not match app_user_id='{app_user_id}' to a User.")
            payment_event.processed = True
            payment_event.save(update_fields=['processed'])
            return Response(
                {"status": "user_not_found", "event_id": event_id},
                status=status.HTTP_200_OK
            )

        # 5. Resolve Plan
        plan = None
        if plan_slug:
            plan = Plan.objects.filter(slug__iexact=plan_slug).first()
        if not plan:
            # Fallback to default Pro plan if specified
            plan = Plan.objects.filter(slug='pro').first()

        if not plan:
            logger.warning(f"[RevenueCatWebhook] No active plan found for slug='{plan_slug}'.")
            payment_event.processed = True
            payment_event.save(update_fields=['processed'])
            return Response(
                {"status": "plan_not_found", "event_id": event_id},
                status=status.HTTP_200_OK
            )

        # 6. Apply Status Transition (Single active subscription per user rule)
        # Deactivate any previous active subscriptions if this is a new active plan
        if sub_status in ('active', 'grace'):
            Subscription.objects.filter(user=user, status__in=['active', 'grace']).exclude(plan=plan).update(status='expired')

        sub, _ = Subscription.objects.get_or_create(
            user=user,
            plan=plan,
            defaults={
                'status': sub_status,
                'provider': 'revenuecat',
                'current_period_end': period_end,
                'provider_subscription_id': event_id,
            }
        )
        sub.status = sub_status
        sub.provider = 'revenuecat'
        if period_end:
            sub.current_period_end = period_end
        sub.provider_subscription_id = event_id
        sub.save()

        payment_event.processed = True
        payment_event.save(update_fields=['processed'])

        logger.info(f"[RevenueCatWebhook] Updated user {user.username} to {plan.slug} ({sub_status}).")
        return Response(
            {
                "status": "processed",
                "event_id": event_id,
                "user_id": user.id,
                "plan": plan.slug,
                "subscription_status": sub_status,
            },
            status=status.HTTP_200_OK
        )


class SubscriptionSyncView(APIView):
    """
    POST /api/subscriptions/sync/
    Client fallback after completing In-App Purchase in case webhook delivery is slow.
    Queries the RevenueCat REST API using REVENUECAT_API_KEY to verify the user's latest entitlements.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        api_key = os.getenv('REVENUECAT_API_KEY', '').strip()
        user = request.user
        app_user_id = str(user.id)

        if api_key:
            try:
                url = f"https://api.revenuecat.com/v1/subscribers/{app_user_id}"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                }
                resp = requests.get(url, headers=headers, timeout=6)
                if resp.status_code == 200:
                    data = resp.json().get('subscriber', {})
                    entitlements = data.get('entitlements', {})

                    # Check for Exclusive or Pro entitlements
                    exclusive_ent = entitlements.get('exclusive', {})
                    pro_ent = entitlements.get('pro', {})

                    matched_slug = None
                    period_end = None

                    if exclusive_ent:
                        matched_slug = 'exclusive'
                        exp_str = exclusive_ent.get('expires_date')
                        if exp_str:
                            from dateutil import parser
                            period_end = parser.parse(exp_str)
                    elif pro_ent:
                        matched_slug = 'pro'
                        exp_str = pro_ent.get('expires_date')
                        if exp_str:
                            from dateutil import parser
                            period_end = parser.parse(exp_str)

                    if matched_slug:
                        plan = Plan.objects.filter(slug=matched_slug).first()
                        if plan:
                            sub, _ = Subscription.objects.get_or_create(
                                user=user,
                                defaults={'plan': plan, 'status': 'active', 'provider': 'revenuecat'}
                            )
                            sub.plan = plan
                            sub.status = 'active'
                            sub.provider = 'revenuecat'
                            if period_end:
                                sub.current_period_end = period_end
                            sub.save()
            except Exception as e:
                logger.warning(f"[SubscriptionSync] RevenueCat REST API sync error: {e}")

        # Return latest /me/ status
        sub = (
            Subscription.objects.filter(user=user)
            .select_related('plan')
            .order_by('-updated_at')
            .first()
        )
        has_sub = sub.is_currently_active if sub else False

        return Response({
            "has_subscription": has_sub,
            "plan": PlanSerializer(sub.plan).data if (sub and sub.plan) else None,
            "status": sub.status if sub else None,
            "current_period_end": sub.current_period_end if sub else None,
            "entitlements": sub.entitlements if sub else {"live_2d": False, "live_vr": False},
        }, status=status.HTTP_200_OK)


class StreamTokenView(APIView):
    """
    GET /api/subscriptions/stream-token/
    Refreshes the short-lived HMAC-SHA256 token for authenticated users viewing live streams.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        path = request.query_params.get('path', '/live/stream.m3u8')
        user_id = request.user.id
        token_payload = StreamSigner.create_token_payload(path, user_id, lifetime_seconds=300)
        return Response(token_payload, status=status.HTTP_200_OK)
