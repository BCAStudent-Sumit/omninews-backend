"""
users/tests.py — Security test suite for authentication and password-reset flows.

Covers:
  * FIX 5: UserProfileView must NOT promote any username to superuser
  * FIX 4: PasswordResetRequestView always returns 200 (no email enumeration)
  * FIX 4: PasswordResetConfirmView verifies token and sets password
  * FIX 4: PasswordResetConfirmView rejects invalid / replayed tokens
  * FIX 4: PasswordResetConfirmView enforces minimum password length
  * Registration happy-path
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core import mail
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()
_token_gen = PasswordResetTokenGenerator()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetTokenFlowTest(APITestCase):
    """End-to-end tests for the two-step token-based password reset."""

    REQUEST_URL = '/api/auth/password-reset/'
    CONFIRM_URL = '/api/auth/password-reset/confirm/'

    def setUp(self):
        self.user = User.objects.create_user(
            username='alice',
            email='alice@example.com',
            password='OldSecurePass1',
        )

    # ------------------------------------------------------------------ step 1
    def test_reset_request_returns_200_for_known_email(self):
        """Known email → 200 OK (token emailed)."""
        resp = self.client.post(self.REQUEST_URL, {'email': 'alice@example.com'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_reset_request_returns_200_for_unknown_email(self):
        """Unknown email must ALSO return 200 — prevents email enumeration."""
        resp = self.client.post(self.REQUEST_URL, {'email': 'nobody@example.com'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_reset_request_sends_email_for_known_address(self):
        """An email containing the uid and token must be sent for a registered address."""
        self.client.post(self.REQUEST_URL, {'email': 'alice@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('alice@example.com', mail.outbox[0].to)
        self.assertIn('uid=', mail.outbox[0].body)
        self.assertIn('token=', mail.outbox[0].body)

    def test_reset_request_sends_no_email_for_unknown_address(self):
        """No email must be sent for an address that has no account."""
        self.client.post(self.REQUEST_URL, {'email': 'ghost@example.com'})
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_request_requires_email_field(self):
        """Missing email field should return 400."""
        resp = self.client.post(self.REQUEST_URL, {})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------ step 2
    def _make_reset_params(self, user=None):
        """Helper: produce valid uid + token for *user* (defaults to self.user)."""
        u = user or self.user
        return {
            'uid': urlsafe_base64_encode(force_bytes(u.pk)),
            'token': _token_gen.make_token(u),
        }

    def test_confirm_sets_new_password(self):
        """Valid uid + token + strong password → password changed, returns 200."""
        params = self._make_reset_params()
        params['new_password'] = 'NewSecurePass99'
        resp = self.client.post(self.CONFIRM_URL, params)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewSecurePass99'))

    def test_confirm_rejects_invalid_token(self):
        """Tampered token must return 400 and NOT change the password."""
        params = self._make_reset_params()
        params['token'] = 'totally-invalid-token'
        params['new_password'] = 'NewSecurePass99'
        resp = self.client.post(self.CONFIRM_URL, params)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('OldSecurePass1'))  # unchanged

    def test_confirm_rejects_invalid_uid(self):
        """Garbage uid must return 400."""
        resp = self.client.post(self.CONFIRM_URL, {
            'uid': 'ZZZinvalidZZZ',
            'token': 'sometoken',
            'new_password': 'NewSecurePass99',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_rejects_short_password(self):
        """New password shorter than 8 chars must return 400."""
        params = self._make_reset_params()
        params['new_password'] = 'short'
        resp = self.client.post(self.CONFIRM_URL, params)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('OldSecurePass1'))  # unchanged

    def test_confirm_token_used_twice_is_rejected(self):
        """After the first successful reset the token must not work again."""
        params = self._make_reset_params()
        params['new_password'] = 'FirstNewPass99'
        # First use — succeeds
        resp1 = self.client.post(self.CONFIRM_URL, params)
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)

        # Second use — same uid + token must fail (last_login changed → hash invalid)
        params['new_password'] = 'SecondNewPass99'
        resp2 = self.client.post(self.CONFIRM_URL, params)
        self.assertEqual(resp2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_requires_both_uid_and_token(self):
        """Missing uid or token must return 400."""
        resp = self.client.post(self.CONFIRM_URL, {'new_password': 'SomeNewPass99'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class SuperuserEscalationTest(APITestCase):
    """
    FIX 5: UserProfileView must NOT auto-promote any username to superuser.
    The old code promoted usernames 'sumit' and 'admin' on every profile load,
    allowing an attacker to register one of those usernames and gain superuser rights.
    """

    PROFILE_URL = '/api/auth/profile/'

    def _create_and_fetch_profile(self, username):
        user = User.objects.create_user(
            username=username,
            password='SafePass123',
        )
        self.client.force_authenticate(user=user)
        resp = self.client.get(self.PROFILE_URL)
        user.refresh_from_db()
        return user, resp

    def test_username_sumit_not_promoted_to_superuser(self):
        user, resp = self._create_and_fetch_profile('sumit')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(user.is_superuser, "Username 'sumit' must NOT be auto-promoted to superuser.")
        self.assertFalse(user.is_staff, "Username 'sumit' must NOT be auto-promoted to staff.")

    def test_username_admin_not_promoted_to_superuser(self):
        user, resp = self._create_and_fetch_profile('admin')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(user.is_superuser, "Username 'admin' must NOT be auto-promoted to superuser.")
        self.assertFalse(user.is_staff, "Username 'admin' must NOT be auto-promoted to staff.")

    def test_ordinary_user_not_promoted(self):
        user, resp = self._create_and_fetch_profile('regularuser')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)

    def test_actual_superuser_stays_superuser(self):
        """A user that was properly granted superuser status must not lose it."""
        user = User.objects.create_superuser(
            username='realadmin',
            password='AdminPass123',
            email='admin@omninews.io',
        )
        self.client.force_authenticate(user=user)
        resp = self.client.get(self.PROFILE_URL)
        user.refresh_from_db()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)

    def test_profile_requires_authentication(self):
        """Anonymous GET on profile must return 401."""
        resp = self.client.get(self.PROFILE_URL)
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class RegistrationTest(APITestCase):
    """Basic registration smoke tests."""

    URL = '/api/auth/register/'

    def test_register_happy_path(self):
        resp = self.client.post(self.URL, {
            'username': 'newuser',
            'email': 'new@example.com',
            'password': 'SecurePass123',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_register_short_password_rejected(self):
        resp = self.client.post(self.URL, {
            'username': 'shortpass',
            'email': 'short@example.com',
            'password': '123',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_username_rejected(self):
        User.objects.create_user(username='taken', password='SomePass123')
        resp = self.client.post(self.URL, {
            'username': 'taken',
            'email': 'other@example.com',
            'password': 'AnotherPass123',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
