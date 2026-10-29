from django.core.cache import cache
import os
import time
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from subscriptions.models import Plan, Subscription, PaymentEvent, VrPairing
from subscriptions.signing import StreamSigner
from news.models import LiveTelecast

User = get_user_model()


class SubscriptionsAndStreamTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testsubscriber',
            email='subscriber@omninews.com',
            password='testpassword123'
        )
        self.pro_plan, _ = Plan.objects.get_or_create(
            slug='pro',
            defaults={
                'name': 'OmniNews Pro',
                'price_inr': 199.00,
                'interval': 'monthly',
                'store_product_id': 'omninews_pro_monthly',
                'features': ['Ad-free', '2D Live Telecast'],
                'active': True,
            }
        )
        self.exclusive_plan, _ = Plan.objects.get_or_create(
            slug='exclusive',
            defaults={
                'name': 'OmniNews Exclusive',
                'price_inr': 499.00,
                'interval': 'monthly',
                'store_product_id': 'omninews_exclusive_monthly',
                'features': ['Everything in Pro', '360 VR Live Telecast'],
                'active': True,
            }
        )
        self.telecast, _ = LiveTelecast.objects.get_or_create(
            id=1,
            defaults={
                'is_live': True,
                'title': 'World Cup Final IND vs AUS',
                'sport': 'Cricket',
                'stream_url': 'https://cdn.omninews.com/live/feed.m3u8',
                'stream_url_vr': 'https://cdn.omninews.com/live/vr_feed.m3u8',
                'required_tier': 'pro',
                'viewers': '25.0K',
            }
        )

    # -------------------------------------------------------------
    # 1. PLANS & ME ENDPOINTS
    # -------------------------------------------------------------
    def test_public_plans_endpoint(self):
        resp = self.client.get('/api/subscriptions/plans/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        slugs = [p['slug'] for p in resp.data]
        self.assertIn('pro', slugs)
        self.assertIn('exclusive', slugs)

    def test_me_endpoint_unauthenticated(self):
        resp = self.client.get('/api/subscriptions/me/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_endpoint_no_subscription(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get('/api/subscriptions/me/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data['has_subscription'])
        self.assertFalse(resp.data['entitlements']['live_2d'])
        self.assertFalse(resp.data['entitlements']['live_vr'])

    def test_me_endpoint_with_active_pro(self):
        Subscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            status='active',
            current_period_end=timezone.now() + timedelta(days=30),
            provider='revenuecat'
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.get('/api/subscriptions/me/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['has_subscription'])
        self.assertEqual(resp.data['plan']['slug'], 'pro')
        self.assertTrue(resp.data['entitlements']['live_2d'])
        self.assertFalse(resp.data['entitlements']['live_vr'])

    def test_me_endpoint_with_active_exclusive(self):
        Subscription.objects.create(
            user=self.user,
            plan=self.exclusive_plan,
            status='active',
            current_period_end=timezone.now() + timedelta(days=30),
            provider='revenuecat'
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.get('/api/subscriptions/me/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['has_subscription'])
        self.assertEqual(resp.data['plan']['slug'], 'exclusive')
        self.assertTrue(resp.data['entitlements']['live_2d'])
        self.assertTrue(resp.data['entitlements']['live_vr'])

    # -------------------------------------------------------------
    # 2. WEBHOOK AUTHENTICATION FAILURE & SUCCESS
    # -------------------------------------------------------------
    @patch.dict(os.environ, {'REVENUECAT_WEBHOOK_AUTH': 'super_secure_webhook_secret_99'}, clear=False)
    def test_webhook_auth_failure_missing_header(self):
        payload = {"event": {"type": "INITIAL_PURCHASE", "id": "evt_test_1"}}
        resp = self.client.post('/api/subscriptions/webhook/revenuecat/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch.dict(os.environ, {'REVENUECAT_WEBHOOK_AUTH': 'super_secure_webhook_secret_99'}, clear=False)
    def test_webhook_auth_failure_wrong_secret(self):
        payload = {"event": {"type": "INITIAL_PURCHASE", "id": "evt_test_1"}}
        resp = self.client.post(
            '/api/subscriptions/webhook/revenuecat/',
            payload,
            format='json',
            HTTP_AUTHORIZATION='Bearer wrong_secret'
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch.dict(os.environ, {'REVENUECAT_WEBHOOK_AUTH': 'super_secure_webhook_secret_99'}, clear=False)
    def test_webhook_auth_success(self):
        payload = {
            "event": {
                "id": "evt_test_auth_success",
                "type": "INITIAL_PURCHASE",
                "app_user_id": str(self.user.id),
                "product_id": "omninews_pro_monthly",
                "expiration_at_ms": int((time.time() + 86400 * 30) * 1000)
            }
        }
        resp = self.client.post(
            '/api/subscriptions/webhook/revenuecat/',
            payload,
            format='json',
            HTTP_AUTHORIZATION='Bearer super_secure_webhook_secret_99'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'processed')

    # -------------------------------------------------------------
    # 3. DUPLICATE EVENT IDEMPOTENCY
    # -------------------------------------------------------------
    @patch.dict(os.environ, {'REVENUECAT_WEBHOOK_AUTH': 'test_webhook_key'}, clear=False)
    def test_duplicate_event_idempotency(self):
        event_id = "evt_idempotent_999"
        payload = {
            "event": {
                "id": event_id,
                "type": "INITIAL_PURCHASE",
                "app_user_id": str(self.user.id),
                "product_id": "omninews_pro_monthly",
                "expiration_at_ms": int((time.time() + 86400 * 30) * 1000)
            }
        }
        # First call -> processed
        resp1 = self.client.post(
            '/api/subscriptions/webhook/revenuecat/',
            payload,
            format='json',
            HTTP_AUTHORIZATION='test_webhook_key'
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(resp1.data['status'], 'processed')
        self.assertEqual(PaymentEvent.objects.filter(event_id=event_id).count(), 1)

        # Second call with identical event_id -> ignored
        resp2 = self.client.post(
            '/api/subscriptions/webhook/revenuecat/',
            payload,
            format='json',
            HTTP_AUTHORIZATION='test_webhook_key'
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.data['status'], 'duplicate_ignored')
        self.assertEqual(PaymentEvent.objects.filter(event_id=event_id).count(), 1)

    # -------------------------------------------------------------
    # 4. STATUS TRANSITIONS
    # -------------------------------------------------------------
    @patch.dict(os.environ, {'REVENUECAT_WEBHOOK_AUTH': 'test_key'}, clear=False)
    def test_status_transitions(self):
        headers = {'HTTP_AUTHORIZATION': 'Bearer test_key'}
        transitions = [
            ("INITIAL_PURCHASE", "active"),
            ("BILLING_ISSUE", "grace"),
            ("RENEWAL", "active"),
            ("CANCELLATION", "cancelled"),
            ("UNCANCELLATION", "active"),
            ("EXPIRATION", "expired"),
        ]

        for idx, (event_type, expected_status) in enumerate(transitions):
            payload = {
                "event": {
                    "id": f"evt_transition_{idx}_{event_type}",
                    "type": event_type,
                    "app_user_id": str(self.user.id),
                    "product_id": "omninews_exclusive_monthly",
                    "expiration_at_ms": int((time.time() + 86400 * 30) * 1000)
                }
            }
            resp = self.client.post('/api/subscriptions/webhook/revenuecat/', payload, format='json', **headers)
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            self.assertEqual(resp.data['subscription_status'], expected_status)

            sub = Subscription.objects.get(user=self.user)
            self.assertEqual(sub.status, expected_status)

    # -------------------------------------------------------------
    # 5. LIVE TELECAST ENTITLEMENT & SIGNED URL CHECKS
    # -------------------------------------------------------------
    def test_telecast_anonymous_user_blocked(self):
        resp = self.client.get('/api/news/live-telecast/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['requires_subscription'])
        self.assertEqual(resp.data['stream_url'], "")
        self.assertEqual(resp.data['stream_url_vr'], "")
        self.assertEqual(resp.data['required_tier'], "pro")

    def test_telecast_unsubscribed_user_blocked(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get('/api/news/live-telecast/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['requires_subscription'])
        self.assertEqual(resp.data['stream_url'], "")
        self.assertEqual(resp.data['stream_url_vr'], "")

    def test_telecast_pro_user_gets_signed_2d_stream_only(self):
        Subscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            status='active',
            current_period_end=timezone.now() + timedelta(days=30),
            provider='revenuecat'
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.get('/api/news/live-telecast/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data['requires_subscription'])
        self.assertIn('token=', resp.data['stream_url'])
        self.assertIn(f'uid={self.user.id}', resp.data['stream_url'])
        self.assertEqual(resp.data['stream_url_vr'], "")  # Pro does not get VR

        # Verify signature validity
        self.assertTrue(StreamSigner.verify_url(resp.data['stream_url'], expected_user_id=self.user.id))

    def test_telecast_exclusive_user_gets_both_signed_streams(self):
        Subscription.objects.create(
            user=self.user,
            plan=self.exclusive_plan,
            status='active',
            current_period_end=timezone.now() + timedelta(days=30),
            provider='revenuecat'
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.get('/api/news/live-telecast/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data['requires_subscription'])
        self.assertIn('token=', resp.data['stream_url'])
        self.assertIn('token=', resp.data['stream_url_vr'])

        # Verify signatures
        self.assertTrue(StreamSigner.verify_url(resp.data['stream_url'], expected_user_id=self.user.id))
        self.assertTrue(StreamSigner.verify_url(resp.data['stream_url_vr'], expected_user_id=self.user.id))

    def test_telecast_exclusive_required_blocks_pro_user(self):
        # Update telecast to require exclusive
        self.telecast.required_tier = 'exclusive'
        self.telecast.save()

        Subscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            status='active',
            current_period_end=timezone.now() + timedelta(days=30),
            provider='revenuecat'
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.get('/api/news/live-telecast/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['requires_subscription'])
        self.assertEqual(resp.data['required_tier'], 'exclusive')
        self.assertEqual(resp.data['stream_url'], "")
        self.assertEqual(resp.data['stream_url_vr'], "")

    # -------------------------------------------------------------
    # 6. SIGNED URL EXPIRY & TAMPERING
    # -------------------------------------------------------------
    def test_signed_url_validity_and_expiry(self):
        url = "https://stream.omninews.com/live/match.m3u8"
        user_id = 42

        # 1. Fresh signed URL passes
        signed = StreamSigner.sign_url(url, user_id=user_id, lifetime_seconds=300)
        self.assertTrue(StreamSigner.verify_url(signed, expected_user_id=user_id))

        # 2. Wrong user ID fails
        self.assertFalse(StreamSigner.verify_url(signed, expected_user_id=999))

        # 3. Expired URL fails
        expired_signed = StreamSigner.sign_url(url, user_id=user_id, lifetime_seconds=-10)
        self.assertFalse(StreamSigner.verify_url(expired_signed, expected_user_id=user_id))

        # 4. Tampered URL path fails
        tampered = signed.replace('/live/match.m3u8', '/live/other.m3u8')
        self.assertFalse(StreamSigner.verify_url(tampered, expected_user_id=user_id))

    def test_stream_token_endpoint(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get('/api/subscriptions/stream-token/?path=/live/feed.m3u8')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('token', resp.data)
        self.assertIn('expires', resp.data)
        self.assertEqual(resp.data['uid'], str(self.user.id))
        self.assertEqual(resp.data['expires_in'], 300)

    # -------------------------------------------------------------
    # 7. VR PAIRING & REDEEM TESTS
    # -------------------------------------------------------------
    @override_settings(VR_ENABLED=False)
    def test_vr_kill_switch_disabled_returns_403(self):
        # 1. vr-pair endpoint
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/subscriptions/vr-pair/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("VR not available yet", resp.data.get("detail", ""))

        # 2. vr-pair redeem endpoint
        resp = self.client.post('/api/subscriptions/vr-pair/redeem/', {'code': '123456'})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("VR not available yet", resp.data.get("detail", ""))

        # 3. stream-token telecast endpoint
        resp = self.client.get(f'/api/subscriptions/stream-token/?telecast={self.telecast.id}')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("VR not available yet", resp.data.get("detail", ""))

    @override_settings(VR_ENABLED=True)
    def test_vr_pair_entitlement_missing_returns_403(self):
        # Unsubscribed user
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/subscriptions/vr-pair/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Pro user (only 2D, lacks live_vr)
        Subscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            status='active',
            current_period_end=timezone.now() + timedelta(days=30),
            provider='revenuecat'
        )
        resp = self.client.post('/api/subscriptions/vr-pair/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(VR_ENABLED=True)
    def test_vr_pair_success_and_expiry(self):
        Subscription.objects.create(
            user=self.user,
            plan=self.exclusive_plan,
            status='active',
            current_period_end=timezone.now() + timedelta(days=30),
            provider='revenuecat'
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/subscriptions/vr-pair/')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('code', resp.data)
        self.assertIn('expires_at', resp.data)
        self.assertEqual(len(resp.data['code']), 6)

        pairing = VrPairing.objects.filter(code=resp.data['code']).first()
        self.assertIsNotNone(pairing)
        self.assertFalse(pairing.used)
        self.assertEqual(pairing.failed_attempts, 0)
        self.assertTrue(pairing.is_valid())

    @override_settings(VR_ENABLED=True)
    def test_vr_redeem_success_and_jwt_scope(self):
        Subscription.objects.create(
            user=self.user,
            plan=self.exclusive_plan,
            status='active',
            current_period_end=timezone.now() + timedelta(days=30),
            provider='revenuecat'
        )
        pairing = VrPairing.objects.create(
            code='654321',
            user=self.user,
            expires_at=timezone.now() + timedelta(minutes=10),
            used=False
        )
        resp = self.client.post('/api/subscriptions/vr-pair/redeem/', {'code': '654321'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access_token', resp.data)
        self.assertIn('user_display_name', resp.data)
        self.assertIn('telecasts', resp.data)

        # Check pairing is marked used
        pairing.refresh_from_db()
        self.assertTrue(pairing.used)

        # Decode token and check claims
        from rest_framework_simplejwt.tokens import AccessToken
        token = AccessToken(resp.data['access_token'])
        self.assertEqual(token.get('scope'), 'vr')
        self.assertIsNotNone(token.get('vr_session_id'))

    @override_settings(VR_ENABLED=True)
    def test_vr_redeem_expired_code_fails(self):
        VrPairing.objects.create(
            code='111222',
            user=self.user,
            expires_at=timezone.now() - timedelta(minutes=1),  # Expired
            used=False
        )
        resp = self.client.post('/api/subscriptions/vr-pair/redeem/', {'code': '111222'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data.get('detail'), "Invalid or expired pairing code.")

    @override_settings(VR_ENABLED=True)
    def test_vr_redeem_reused_code_fails(self):
        VrPairing.objects.create(
            code='222333',
            user=self.user,
            expires_at=timezone.now() + timedelta(minutes=10),
            used=True  # Already used
        )
        resp = self.client.post('/api/subscriptions/vr-pair/redeem/', {'code': '222333'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data.get('detail'), "Invalid or expired pairing code.")

    @override_settings(VR_ENABLED=True)
    def test_vr_redeem_brute_force_invalidates_code(self):
        pairing = VrPairing.objects.create(
            code='333444',
            user=self.user,
            expires_at=timezone.now() + timedelta(minutes=10),
            used=False,
            failed_attempts=5  # Reached threshold
        )
        resp = self.client.post('/api/subscriptions/vr-pair/redeem/', {'code': '333444'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data.get('detail'), "Invalid or expired pairing code.")
        pairing.refresh_from_db()
        self.assertTrue(pairing.used)

    @override_settings(VR_ENABLED=True)
    def test_vr_concurrent_session_invalidation(self):
        Subscription.objects.create(
            user=self.user,
            plan=self.exclusive_plan,
            status='active',
            current_period_end=timezone.now() + timedelta(days=30),
            provider='revenuecat'
        )

        # Session 1
        p1 = VrPairing.objects.create(
            code='101010',
            user=self.user,
            expires_at=timezone.now() + timedelta(minutes=10),
            used=False
        )
        resp1 = self.client.post('/api/subscriptions/vr-pair/redeem/', {'code': '101010'})
        token1 = resp1.data['access_token']

        # Session 2 (supersedes session 1)
        p2 = VrPairing.objects.create(
            code='202020',
            user=self.user,
            expires_at=timezone.now() + timedelta(minutes=10),
            used=False
        )
        resp2 = self.client.post('/api/subscriptions/vr-pair/redeem/', {'code': '202020'})
        token2 = resp2.data['access_token']

        # Attempt stream-token with token1 (superseded)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token1}')
        resp_st1 = self.client.get(f'/api/subscriptions/stream-token/?telecast={self.telecast.id}')
        self.assertEqual(resp_st1.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt stream-token with token2 (active)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token2}')
        resp_st2 = self.client.get(f'/api/subscriptions/stream-token/?telecast={self.telecast.id}')
        self.assertEqual(resp_st2.status_code, status.HTTP_200_OK)
        self.assertIn('stream_url_vr', resp_st2.data)

    @override_settings(VR_ENABLED=True)
    def test_vr_redeem_throttling(self):
        cache.clear()
        for i in range(10):
            resp = self.client.post('/api/subscriptions/vr-pair/redeem/', {'code': '000000'})
            self.assertNotEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        resp_throttled = self.client.post('/api/subscriptions/vr-pair/redeem/', {'code': '000000'})
        self.assertEqual(resp_throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_live_scores_endpoint_cached(self):
        cache.clear()
        resp1 = self.client.get('/api/news/live-scores/')
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertIsInstance(resp1.data, list)
        self.assertGreater(len(resp1.data), 0)
        match = resp1.data[0]
        self.assertIn('id', match)
        self.assertIn('sport', match)
        self.assertIn('home', match)
        self.assertIn('away', match)
        self.assertIn('home_score', match)
        self.assertIn('away_score', match)
        self.assertIn('status', match)
        self.assertIn('overs/period', match)
        self.assertIn('updated_at', match)

        # Subsequent call uses cache
        resp2 = self.client.get('/api/news/live-scores/')
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp1.data, resp2.data)
