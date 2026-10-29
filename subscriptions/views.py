import uuid
import secrets
import datetime
from django.conf import settings
from django.core.cache import cache
from rest_framework.throttling import AnonRateThrottle
from .models import VrPairing
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


class VrPairRedeemThrottle(AnonRateThrottle):
    scope = 'vr_pair_redeem'


class VrPairView(APIView):
    """
    POST /api/subscriptions/vr-pair/
    Auth required. Creates an active 6-digit VR pairing code valid for 10 minutes.
    Requires active Exclusive plan with live_vr entitlement and VR_ENABLED=True.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not getattr(settings, 'VR_ENABLED', False):
            return Response({"detail": "VR not available yet"}, status=status.HTTP_403_FORBIDDEN)

        # Verify live_vr entitlement
        sub = (
            Subscription.objects.filter(user=request.user)
            .select_related('plan')
            .order_by('-updated_at')
            .first()
        )
        if not (sub and sub.entitlements.get('live_vr', False)):
            return Response(
                {"detail": "Exclusive subscription with live_vr entitlement required."},
                status=status.HTTP_403_FORBIDDEN
            )

        now = timezone.now()
        # Invalidate any prior unused active codes for this user
        VrPairing.objects.filter(user=request.user, used=False).update(used=True)

        # Generate unique active 6-digit code
        while True:
            code = f"{secrets.randbelow(900000) + 100000}"
            if not VrPairing.objects.filter(code=code, used=False, expires_at__gt=now).exists():
                break

        expires_at = now + datetime.timedelta(minutes=10)
        pairing = VrPairing.objects.create(
            code=code,
            user=request.user,
            expires_at=expires_at,
            used=False,
            failed_attempts=0
        )

        return Response({
            "code": pairing.code,
            "expires_at": pairing.expires_at.isoformat(),
        }, status=status.HTTP_201_CREATED)


class VrPairRedeemView(APIView):
    """
    POST /api/subscriptions/vr-pair/redeem/
    Public, throttled 10/min per IP.
    After 5 failed attempts on a code, invalidates it.
    On success marks used and returns {access_token (JWT, 1 hour, scope "vr"), user_display_name, telecasts: [...]}.
    Concurrent sessions: allow 1 active VR session per user; a new redeem ends the old one.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [VrPairRedeemThrottle]

    def post(self, request):
        if not getattr(settings, 'VR_ENABLED', False):
            return Response({"detail": "VR not available yet"}, status=status.HTTP_403_FORBIDDEN)

        code = str(request.data.get('code', '')).strip()
        if not code or len(code) != 6:
            return Response({"detail": "Invalid or expired pairing code."}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        pairing = VrPairing.objects.filter(code=code).order_by('-created_at').first()

        # If pairing doesn't exist, generic 400
        if not pairing:
            return Response({"detail": "Invalid or expired pairing code."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if already invalidated by attempts >= 5
        if pairing.failed_attempts >= 5:
            if not pairing.used:
                pairing.used = True
                pairing.save(update_fields=['used'])
            return Response({"detail": "Invalid or expired pairing code."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if expired or used
        if pairing.used or pairing.expires_at <= now:
            return Response({"detail": "Invalid or expired pairing code."}, status=status.HTTP_400_BAD_REQUEST)

        # Verify user still has live_vr entitlement
        sub = (
            Subscription.objects.filter(user=pairing.user)
            .select_related('plan')
            .order_by('-updated_at')
            .first()
        )
        if not (sub and sub.entitlements.get('live_vr', False)):
            pairing.failed_attempts += 1
            if pairing.failed_attempts >= 5:
                pairing.used = True
            pairing.save()
            return Response({"detail": "Invalid or expired pairing code."}, status=status.HTTP_400_BAD_REQUEST)

        # Mark code as used
        pairing.used = True
        pairing.save(update_fields=['used'])

        # Concurrent session management: 1 active VR session per user; new redeem ends old one
        vr_session_id = uuid.uuid4().hex
        cache_key = f"active_vr_session_{pairing.user_id}"
        cache.set(cache_key, vr_session_id, timeout=3600)

        # Issue 1-hour JWT token with scope='vr' and vr_session_id
        from rest_framework_simplejwt.tokens import AccessToken
        token = AccessToken.for_user(pairing.user)
        token.set_exp(lifetime=datetime.timedelta(hours=1))
        token['scope'] = 'vr'
        token['vr_session_id'] = vr_session_id

        user_display_name = (
            pairing.user.get_full_name()
            or pairing.user.username
            or "VR User"
        )

        from news.models import LiveTelecast
        telecasts_qs = LiveTelecast.objects.all().order_by('-is_live', '-id')
        telecasts = [
            {
                "id": t.id,
                "title": t.title,
                "sport": t.sport,
                "is_live": t.is_live,
                "required_tier": getattr(t, 'required_tier', 'pro'),
                "viewers": t.viewers,
            }
            for t in telecasts_qs
        ]

        return Response({
            "access_token": str(token),
            "user_display_name": user_display_name,
            "telecasts": telecasts,
        }, status=status.HTTP_200_OK)


class StreamTokenView(APIView):
    """
    GET /api/subscriptions/stream-token/?telecast=<id>
    GET /api/subscriptions/stream-token/?path=<path>
    VR token or normal auth.
    Returns a signed stream URL valid for 5 minutes, only if:
    - user has live_vr entitlement
    - telecast is not killed and time window is open (is_live=True)
    - VR_ENABLED is True (if VR telecast requested or VR token used)
    Never logs raw stream URLs.
    Concurrent sessions: validates VR session if VR token used.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        telecast_id = request.query_params.get('telecast')

        # Check VR Token & Concurrent Sessions
        vr_session_id = None
        is_vr_token = False
        if hasattr(request, 'auth') and request.auth:
            try:
                is_vr_token = request.auth.get('scope') == 'vr'
                vr_session_id = request.auth.get('vr_session_id')
            except Exception:
                pass

        if not is_vr_token:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                try:
                    from rest_framework_simplejwt.tokens import AccessToken
                    raw_token = AccessToken(auth_header.split(' ', 1)[1])
                    if raw_token.get('scope') == 'vr':
                        is_vr_token = True
                        vr_session_id = raw_token.get('vr_session_id')
                except Exception:
                    pass

        if is_vr_token:
            cached_session = cache.get(f"active_vr_session_{request.user.id}")
            if not cached_session or cached_session != vr_session_id:
                return Response(
                    {"detail": "VR session terminated due to concurrent login or expiration."},
                    status=status.HTTP_401_UNAUTHORIZED
                )

        if telecast_id or is_vr_token:
            # VR Endpoint - Check VR_ENABLED kill switch
            if not getattr(settings, 'VR_ENABLED', False):
                return Response({"detail": "VR not available yet"}, status=status.HTTP_403_FORBIDDEN)

            # Check user's live_vr entitlement
            sub = (
                Subscription.objects.filter(user=request.user)
                .select_related('plan')
                .order_by('-updated_at')
                .first()
            )
            if not (sub and sub.entitlements.get('live_vr', False)):
                return Response(
                    {"detail": "Exclusive subscription with live_vr entitlement required."},
                    status=status.HTTP_403_FORBIDDEN
                )

            if not telecast_id:
                return Response({"detail": "telecast query parameter required."}, status=status.HTTP_400_BAD_REQUEST)

            from news.models import LiveTelecast
            telecast = LiveTelecast.objects.filter(id=telecast_id).first()
            if not telecast:
                return Response({"detail": "Telecast not found."}, status=status.HTTP_404_NOT_FOUND)

            # Check telecast is not killed and time window is open
            if not telecast.is_live:
                return Response({"detail": "Telecast is not live or has ended."}, status=status.HTTP_403_FORBIDDEN)

            raw_stream_url = telecast.stream_url_vr or telecast.stream_url
            if not raw_stream_url:
                return Response({"detail": "VR stream URL not available for this telecast."}, status=status.HTTP_404_NOT_FOUND)

            # Sign stream URL for 5 minutes (300 seconds)
            signed_url = StreamSigner.sign_url(raw_stream_url, user_id=request.user.id, lifetime_seconds=300)

            # NEVER log raw stream URLs!
            logger.info(f"[StreamTokenView] Generated signed VR stream URL for user {request.user.id}, telecast {telecast.id}")

            return Response({
                "stream_url": signed_url,
                "stream_url_vr": signed_url,
                "expires_in": 300,
                "telecast_id": telecast.id,
            }, status=status.HTTP_200_OK)

        # Standard 2D token generation for backwards compatibility
        path = request.query_params.get('path', '/live/stream.m3u8')
        user_id = request.user.id
        token_payload = StreamSigner.create_token_payload(path, user_id, lifetime_seconds=300)
        return Response(token_payload, status=status.HTTP_200_OK)
