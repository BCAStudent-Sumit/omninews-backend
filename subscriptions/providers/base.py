import os
import hmac
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, Tuple, Any

from django.conf import settings
from subscriptions.models import Plan

logger = logging.getLogger(__name__)


class PaymentProvider(ABC):
    """
    Abstract Payment Provider interface.
    Decouples payment processors (RevenueCat, Stripe, etc.) from views and models.
    """

    @abstractmethod
    def verify_webhook(self, request) -> bool:
        """
        Verify incoming webhook signature/authorization.
        Must use constant-time comparisons to prevent timing attacks.
        """
        pass

    @abstractmethod
    def parse_event(self, payload: dict) -> Tuple[Optional[str], Optional[str], str, Optional[datetime], str]:
        """
        Extract normalized subscription details from processor payload.
        Returns:
            (user_id, plan_slug, status, period_end, event_id)
        """
        pass


class RevenueCatProvider(PaymentProvider):
    """
    RevenueCat In-App Purchases & Subscriptions Provider.
    Handles App Store & Google Play webhooks mediated by RevenueCat.
    """

    def verify_webhook(self, request) -> bool:
        expected_secret = os.getenv('REVENUECAT_WEBHOOK_AUTH', '').strip()
        if not expected_secret:
            # If webhook auth is not set in environment, fail closed for security
            logger.warning("[RevenueCatProvider] REVENUECAT_WEBHOOK_AUTH is not configured in env.")
            return False

        auth_header = (
            request.headers.get('Authorization')
            or request.META.get('HTTP_AUTHORIZATION')
            or ''
        ).strip()

        if not auth_header:
            return False

        # Support both raw secret string and 'Bearer <secret>'
        candidate = auth_header
        if candidate.lower().startswith('bearer '):
            candidate = candidate[7:].strip()

        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(candidate, expected_secret)

    def parse_event(self, payload: dict) -> Tuple[Optional[str], Optional[str], str, Optional[datetime], str]:
        event = payload.get('event', payload)

        event_id = str(event.get('id') or '').strip()
        event_type = str(event.get('type') or '').strip().upper()
        app_user_id = str(event.get('app_user_id') or '').strip()
        product_id = str(event.get('product_id') or '').strip()
        expiration_at_ms = event.get('expiration_at_ms')

        # Status transition mapping:
        # INITIAL_PURCHASE, RENEWAL, UNCANCELLATION -> active
        # BILLING_ISSUE -> grace
        # CANCELLATION -> cancelled (still active until period end)
        # EXPIRATION -> expired
        if event_type in ('INITIAL_PURCHASE', 'RENEWAL', 'UNCANCELLATION', 'NON_RENEWING_PURCHASE'):
            status = 'active'
        elif event_type == 'BILLING_ISSUE':
            status = 'grace'
        elif event_type == 'CANCELLATION':
            status = 'cancelled'
        elif event_type == 'EXPIRATION':
            status = 'expired'
        else:
            status = 'active'

        # Convert epoch milliseconds to timezone-aware UTC datetime
        period_end = None
        if expiration_at_ms:
            try:
                period_end = datetime.fromtimestamp(float(expiration_at_ms) / 1000.0, tz=timezone.utc)
            except Exception as e:
                logger.warning(f"[RevenueCatProvider] Could not parse expiration_at_ms {expiration_at_ms}: {e}")

        # Resolve Plan by store_product_id or slug
        plan_slug = None
        if product_id:
            plan = Plan.objects.filter(store_product_id=product_id).first()
            if not plan:
                plan = Plan.objects.filter(slug__iexact=product_id).first()
            if plan:
                plan_slug = plan.slug
            else:
                # Fallback to slug if product_id contains slug name (e.g. omninews_exclusive_monthly)
                p_lower = product_id.lower()
                if 'exclusive' in p_lower:
                    plan_slug = 'exclusive'
                elif 'pro' in p_lower:
                    plan_slug = 'pro'
                else:
                    plan_slug = product_id

        return app_user_id, plan_slug, status, period_end, event_id


class StripeProvider(PaymentProvider):
    """
    Stripe Webhook & Checkout Provider Stub.
    Ready for future expansion without modifying views or subscription models.
    """

    def verify_webhook(self, request) -> bool:
        webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET', '').strip()
        if not webhook_secret:
            return False
        # Stub: when stripe package is wired, verify with stripe.Webhook.construct_event
        return False

    def parse_event(self, payload: dict) -> Tuple[Optional[str], Optional[str], str, Optional[datetime], str]:
        # Stub: parse Stripe customer.subscription.updated / checkout.session.completed
        event_id = str(payload.get('id', ''))
        return None, None, 'active', None, event_id
