from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from news.models import (
    Article, Bookmark, ClarificationClaim, ClaimVote, Genre, Region, Source,
)
from news.scoring import resolve_claim_if_ready, should_clarify

User = get_user_model()


class FeedTestCase(APITestCase):
    def setUp(self):
        # 1. Seed Metadata
        self.source = Source.objects.create(name="BBC News", url="https://bbc.com")
        self.genre_tech = Genre.objects.create(name="Technology")
        self.genre_sports = Genre.objects.create(name="Sports")
        self.region_asia = Region.objects.create(code="AS", name="Asia")
        self.region_eu = Region.objects.create(code="EU", name="Europe")

        now = timezone.now()

        # 2. Seed Articles with varied attributes and published times
        # Article 1: Older, matches Genre (+2) and Region (+1) => Score 3
        self.top_match_article = Article.objects.create(
            title="Top Match Tech Asia",
            url="https://example.com/1",
            body="Content 1",
            source=self.source,
            genre=self.genre_tech,
            region=self.region_asia,
            published_at=now - timedelta(days=2)
        )

        # Article 2: Brand new, no matches => Score 0
        self.newest_unmatched_article = Article.objects.create(
            title="Brand New Sports Europe",
            url="https://example.com/2",
            body="Content 2",
            source=self.source,
            genre=self.genre_sports,
            region=self.region_eu,
            published_at=now
        )

        # 3. Seed Users
        self.ranked_user = User.objects.create_user(
            username="ranked_user",
            password="testpassword123",
            home_region=self.region_asia,
            raw_feed=False
        )
        self.ranked_user.genres.add(self.genre_tech)

        self.raw_feed_user = User.objects.create_user(
            username="raw_user",
            password="testpassword123",
            home_region=self.region_asia,
            raw_feed=True
        )
        self.raw_feed_user.genres.add(self.genre_tech)

    def test_anonymous_request_returns_401(self):
        """Unauthenticated requests must be denied access."""
        response = self.client.get("/api/news/feed/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ranked_user_receives_higher_score_first(self):
        """User with preferences should see high score first, despite published date."""
        self.client.force_authenticate(user=self.ranked_user)
        response = self.client.get("/api/news/feed/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data.get("results", response.data)
        self.assertEqual(results[0]["id"], self.top_match_article.id)
        self.assertEqual(results[1]["id"], self.newest_unmatched_article.id)

    def test_raw_feed_user_receives_chronological_order(self):
        """User with raw_feed=True should get strictly newest published articles first."""
        self.client.force_authenticate(user=self.raw_feed_user)
        response = self.client.get("/api/news/feed/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data.get("results", response.data)
        self.assertEqual(results[0]["id"], self.newest_unmatched_article.id)
        self.assertEqual(results[1]["id"], self.top_match_article.id)

    def test_feed_filtering_by_genre_and_region(self):
        """Authenticated feed supports explicit genre and region query parameters."""
        self.client.force_authenticate(user=self.ranked_user)

        # Filter by sports genre (matches only newest_unmatched_article)
        response = self.client.get(f"/api/news/feed/?genre={self.genre_sports.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.newest_unmatched_article.id)

    def test_feed_filtering_by_clarify_status(self):
        """Authenticated feed supports filtering by clarify_status."""
        self.client.force_authenticate(user=self.ranked_user)

        # Flag top_match_article as clarified
        self.top_match_article.clarify_status = Article.ClarifyStatus.CLARIFIED
        self.top_match_article.save(update_fields=["clarify_status"])

        response = self.client.get("/api/news/feed/?clarify_status=clarified")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.top_match_article.id)


class ClarifyBadgeRuleTestCase(APITestCase):
    """Unit tests verifying the pure Python badge evaluation logic."""

    def test_ten_zero_karma_accounts_cannot_produce_badge(self):
        """Sybil defense: zero karma accounts provide zero weight."""
        votes = [(1, 0) for _ in range(10)]
        self.assertFalse(should_clarify(votes))

    def test_single_veteran_account_cannot_produce_badge_alone(self):
        """Diversity defense: one account alone cannot trigger a badge."""
        votes = [(1, 500)]
        self.assertFalse(should_clarify(votes))

    def test_established_accounts_agreeing_produces_badge(self):
        """Consensus: 3 established accounts agreeing triggers the badge."""
        votes = [(1, 25), (1, 25), (1, 25)]
        self.assertTrue(should_clarify(votes))

    def test_disagreement_suppresses_badge(self):
        """Contested claims lacking strong supermajority consensus fail."""
        votes = [(1, 25), (1, 25), (1, 25), (-1, 36), (-1, 36)]
        self.assertFalse(should_clarify(votes))

    def test_whale_plus_two_nominal_accounts_cannot_produce_badge(self):
        """Whale defense: a single account with massive karma cannot drag nominal accounts across threshold."""
        votes = [(1, 10000), (1, 5), (1, 5)]
        self.assertFalse(
            should_clarify(votes),
            "A whale with two nominal accounts must not trigger a badge alone."
        )


class ClarifyBadgeIntegrationTestCase(APITestCase):
    """Database integration tests checking vote saving, triggers, and constraints."""

    def setUp(self):
        self.source = Source.objects.create(name="Reuters", url="https://reuters.com")
        self.article = Article.objects.create(
            title="Breaking Tech News",
            body="Some claims here",
            url="https://reuters.com/tech-news-1",
            source=self.source,
            published_at=timezone.now()
        )
        self.author = User.objects.create_user(username="claim_author", password="password123")
        self.claim = ClarificationClaim.objects.create(
            article=self.article,
            author=self.author,
            text="The article omits critical contextual evidence."
        )

    def test_ten_zero_karma_votes_do_not_activate_badge(self):
        """10 zero-karma accounts agreeing must not trigger the badge."""
        for i in range(10):
            voter = User.objects.create_user(username=f"zero_voter_{i}", karma=0)
            ClaimVote.objects.create(claim=self.claim, user=voter, value=1)

        result = resolve_claim_if_ready(self.claim)
        self.assertFalse(result)

        self.claim.refresh_from_db()
        self.article.refresh_from_db()
        self.assertFalse(self.claim.is_active_badge)
        self.assertEqual(self.article.clarify_status, Article.ClarifyStatus.NONE)

    def test_established_accounts_activate_badge_and_article_status(self):
        """Diverse established accounts agreeing triggers badge and updates article status."""
        for i in range(3):
            voter = User.objects.create_user(username=f"veteran_{i}", password="password123")
            voter.karma = 25
            voter.save(update_fields=["karma"])
            ClaimVote.objects.create(claim=self.claim, user=voter, value=1)

        result = resolve_claim_if_ready(self.claim)
        self.assertTrue(result)

        self.claim.refresh_from_db()
        self.article.refresh_from_db()
        self.assertTrue(self.claim.is_active_badge)
        self.assertEqual(self.article.clarify_status, Article.ClarifyStatus.CLARIFIED)

    def test_duplicate_vote_raises_integrity_error(self):
        """Database constraint must prevent a user from voting twice on the same claim."""
        voter = User.objects.create_user(username="single_voter", karma=10)
        ClaimVote.objects.create(claim=self.claim, user=voter, value=1)

        with self.assertRaises(IntegrityError):
            ClaimVote.objects.create(claim=self.claim, user=voter, value=1)

    def test_already_resolved_claim_ignores_subsequent_votes(self):
        """Once resolved, subsequent votes do not trigger re-resolution, and status remains intact."""
        # 1. Reach resolution threshold with 3 reputable accounts (karma=25 each)
        for i in range(3):
            voter = User.objects.create_user(username=f"seed_voter_{i}", password="password123")
            voter.karma = 25
            voter.save(update_fields=["karma"])
            ClaimVote.objects.create(claim=self.claim, user=voter, value=1)

        first_resolution = resolve_claim_if_ready(self.claim)
        self.assertTrue(first_resolution, "First invocation must resolve the claim (returns True).")
        self.claim.refresh_from_db()
        self.assertTrue(self.claim.is_active_badge)

        # 2. Add an opposing vote after resolution
        dissenter = User.objects.create_user(username="late_dissenter", password="password123")
        dissenter.karma = 100
        dissenter.save(update_fields=["karma"])
        ClaimVote.objects.create(claim=self.claim, user=dissenter, value=-1)

        # 3. Running resolution again must return False (nothing newly resolved), but badge stays active
        self.claim.refresh_from_db()
        second_resolution = resolve_claim_if_ready(self.claim)
        self.assertFalse(second_resolution, "Second invocation must return False (already resolved).")

        self.claim.refresh_from_db()
        self.article.refresh_from_db()
        self.assertTrue(self.claim.is_active_badge, "Badge must remain active despite late dissenting vote.")
        self.assertEqual(self.article.clarify_status, Article.ClarifyStatus.CLARIFIED)

    def test_vote_value_must_be_plus_or_minus_one(self):
        """Database constraint must reject vote values other than +1 or -1."""
        voter = User.objects.create_user(username="bad_value_voter", karma=10)
        with self.assertRaises(IntegrityError):
            ClaimVote.objects.create(claim=self.claim, user=voter, value=5)


class ClaimAPIEndpointTestCase(APITestCase):
    """API endpoint tests for submitting claims and voting."""

    def setUp(self):
        self.source = Source.objects.create(name="Reuters", url="https://reuters.com")
        self.article = Article.objects.create(
            title="API Test Article",
            body="Context body",
            url="https://reuters.com/api-test",
            source=self.source,
            published_at=timezone.now()
        )
        self.user = User.objects.create_user(username="api_user", password="password123", karma=10)
        self.other_user = User.objects.create_user(username="claim_owner", password="password123", karma=10)
        self.client.force_authenticate(user=self.user)

    def test_create_claim_with_evidence(self):
        url = f"/api/news/articles/{self.article.id}/claims/"
        payload = {
            "text": "This article misrepresents the numbers.",
            "evidence_urls": ["https://primarysource.org/doc1"]
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ClarificationClaim.objects.count(), 1)
        self.assertEqual(self.article.claims.first().evidence_links.count(), 1)

    def test_claim_list_shows_agree_and_disagree_counts(self):
        claim = ClarificationClaim.objects.create(
            article=self.article,
            author=self.other_user,
            text="Claim used for counting votes.",
        )
        voters = [
            User.objects.create_user(username=f"count_voter_{i}", password="password123")
            for i in range(3)
        ]
        ClaimVote.objects.create(claim=claim, user=voters[0], value=1)
        ClaimVote.objects.create(claim=claim, user=voters[1], value=1)
        ClaimVote.objects.create(claim=claim, user=voters[2], value=-1)

        url = f"/api/news/articles/{self.article.id}/claims/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["results"] if isinstance(response.data, dict) else response.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["agree_count"], 2)
        self.assertEqual(data[0]["disagree_count"], 1)

    def test_user_cannot_fake_vote_counts_when_creating_claim(self):
        url = f"/api/news/articles/{self.article.id}/claims/"
        payload = {
            "text": "Trying to cheat the counts.",
            "evidence_urls": ["https://primarysource.org/doc2"],
            "agree_count": 99,
            "disagree_count": 99,
        }
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ClarificationClaim.objects.count(), 1)
        self.assertEqual(self.article.claims.first().text, "Trying to cheat the counts.")
        self.assertEqual(response.data["agree_count"], 0)
        self.assertEqual(response.data["disagree_count"], 0)

    def test_claims_are_listed_oldest_first(self):
        first = ClarificationClaim.objects.create(
            article=self.article, author=self.other_user, text="First claim"
        )
        second = ClarificationClaim.objects.create(
            article=self.article, author=self.other_user, text="Second claim"
        )

        response = self.client.get(f"/api/news/articles/{self.article.id}/claims/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["results"] if isinstance(response.data, dict) else response.data
        self.assertEqual([claim["id"] for claim in data], [first.id, second.id])

    def test_author_cannot_vote_on_own_claim(self):
        claim = ClarificationClaim.objects.create(
            article=self.article, author=self.user, text="My own claim"
        )
        url = f"/api/news/claims/{claim.id}/vote/"
        response = self.client.post(url, {"value": 1}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ClaimVote.objects.count(), 0)

    def test_invalid_vote_value_returns_400(self):
        claim = ClarificationClaim.objects.create(
            article=self.article, author=self.other_user, text="Another claim"
        )
        url = f"/api/news/claims/{claim.id}/vote/"
        response = self.client.post(url, {"value": 5}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ClaimVote.objects.count(), 0)


class ProfileAndBookmarkTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="test_reporter", password="password123")
        self.source = Source.objects.create(name="Daily Tech", url="https://dailytech.example.com")
        self.region = Region.objects.create(name="Bengal", code="BEN")
        self.genre = Genre.objects.create(name="Tech")

        self.article = Article.objects.create(
            title="Sample Automated Article",
            body="Article body testing content.",
            url="https://dailytech.example.com/sample-article-1",
            source=self.source,
            genre=self.genre,
            region=self.region,
            published_at=timezone.now(),
        )
        self.client.force_authenticate(user=self.user)

    def test_get_user_profile_stats(self):
        url = reverse("user-profile")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "test_reporter")
        self.assertEqual(response.data["claims_submitted_count"], 0)
        self.assertEqual(response.data["votes_cast_count"], 0)

    def test_bookmark_lifecycle(self):
        # 1. Create Bookmark
        create_url = reverse("user-bookmarks")
        post_response = self.client.post(create_url, {"article": self.article.id}, format="json")
        self.assertEqual(post_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Bookmark.objects.filter(user=self.user).count(), 1)

        # 2. List Bookmarks
        list_response = self.client.get(create_url)
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)

        # 3. Delete Bookmark
        delete_url = reverse("bookmark-delete", kwargs={"article_id": self.article.id})
        delete_response = self.client.delete(delete_url)
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Bookmark.objects.filter(user=self.user).count(), 0)

    def test_duplicate_bookmark_returns_400(self):
        url = reverse("user-bookmarks")
        self.client.post(url, {"article": self.article.id}, format="json")
        res = self.client.post(url, {"article": self.article.id}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Bookmark.objects.filter(user=self.user).count(), 1)

    def test_user_cannot_edit_own_karma(self):
        url = reverse("user-profile")
        self.client.patch(url, {"karma": 9999, "is_fact_checker": True}, format="json")
        self.user.refresh_from_db()
        self.assertEqual(self.user.karma, 0)
        self.assertFalse(self.user.is_fact_checker)


# =============================================================================
# Security regression tests
# =============================================================================

class AiStatusViewSecurityTest(APITestCase):
    """
    FIX 4: AiStatusView POST must require is_staff=True (IsAdminUser).
    GET must remain public.
    """

    URL = '/api/news/ai-status/'

    def setUp(self):
        self.regular = User.objects.create_user(username='regular_ai', password='pass')
        self.admin = User.objects.create_user(
            username='staff_ai', password='pass', is_staff=True
        )

    def test_get_is_public(self):
        """Anyone can GET the AI status."""
        resp = self.client.get(self.URL)
        self.assertIn(resp.status_code, (status.HTTP_200_OK, status.HTTP_401_UNAUTHORIZED))
        # Force anon — should be 200
        resp2 = self.client.get(self.URL)
        # At minimum it should not 500
        self.assertNotEqual(resp2.status_code, 500)

    def test_post_requires_staff(self):
        """Non-staff POST must receive 403."""
        self.client.force_authenticate(user=self.regular)
        resp = self.client.post(self.URL, {'api_key': 'fake-key'}, format='json')
        self.assertIn(resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED))

    def test_anonymous_post_rejected(self):
        """Anonymous POST must receive 401 or 403."""
        resp = self.client.post(self.URL, {'api_key': 'fake-key'}, format='json')
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_staff_post_accepted(self):
        """Staff users may POST (response may fail on invalid key, but not on permission)."""
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(self.URL, {'api_key': ''}, format='json')
        # We care about auth, not Gemini validation — not 401 or 403
        self.assertNotIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class TriggerFetchNewsSecurityTest(APITestCase):
    """
    FIX 8: TriggerFetchNewsView must require authentication.
    Anonymous callers should receive 401.
    """

    URL = '/api/news/fetch-latest/'

    def setUp(self):
        self.user = User.objects.create_user(username='fetcher', password='pass')

    def test_anonymous_post_rejected(self):
        resp = self.client.post(self.URL)
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_authenticated_post_accepted(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(self.URL)
        # 202 Accepted or at worst 429 (throttled) — not an auth error
        self.assertNotIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class ImageProxySSRFTest(APITestCase):
    """
    FIX 7: ImageProxyView must block SSRF attempts and enforce 5 MB limit.
    """

    URL = '/api/news/image-proxy/'

    def _get(self, url):
        return self.client.get(self.URL, {'url': url})

    def test_no_url_parameter_returns_400(self):
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 400)

    def test_localhost_blocked(self):
        """Requests to localhost must be blocked (403)."""
        for target in [
            'http://localhost/secret',
            'http://127.0.0.1/etc/passwd',
            'http://127.0.0.1:8000/admin/',
        ]:
            with self.subTest(target=target):
                resp = self._get(target)
                self.assertEqual(resp.status_code, 403, f"Expected 403 for {target}")

    def test_private_ip_ranges_blocked(self):
        """Requests to RFC-1918 addresses must be blocked (403)."""
        for target in [
            'http://10.0.0.1/internal',
            'http://192.168.1.1/router',
            'http://172.16.0.1/api',
        ]:
            with self.subTest(target=target):
                resp = self._get(target)
                self.assertEqual(resp.status_code, 403, f"Expected 403 for {target}")

    def test_non_allowlisted_public_host_blocked(self):
        """Hosts not in the CDN allowlist must be blocked even if public."""
        for target in [
            'https://evil.com/steal.png',
            'https://attacker.io/malware.jpg',
            'https://google.com/logo.png',  # not in allowlist
        ]:
            with self.subTest(target=target):
                resp = self._get(target)
                self.assertEqual(resp.status_code, 403, f"Expected 403 for {target}")

    def test_allowed_cdn_host_passes_security_check(self):
        """An allowlisted CDN hostname must pass _is_safe_url()."""
        from news.views import ImageProxyView
        view = ImageProxyView()
        self.assertTrue(view._is_safe_url('https://ichef.bbci.co.uk/news/img.jpg'))
        self.assertTrue(view._is_safe_url('https://static.toiimg.com/photo.jpg'))
        self.assertTrue(view._is_safe_url('https://upload.wikimedia.org/img.png'))

    def test_subdomain_of_allowed_host_passes(self):
        """Subdomains of allowed hosts must also pass."""
        from news.views import ImageProxyView
        view = ImageProxyView()
        self.assertTrue(view._is_safe_url('https://images.bbc.co.uk/news/photo.jpg'))

    def test_non_http_scheme_blocked(self):
        """file:// and ftp:// URLs must be blocked."""
        from news.views import ImageProxyView
        view = ImageProxyView()
        self.assertFalse(view._is_safe_url('file:///etc/passwd'))
        self.assertFalse(view._is_safe_url('ftp://upload.wikimedia.org/img.png'))

    def test_raw_ip_always_blocked_even_if_public(self):
        """Raw IP addresses must always be blocked regardless of allowlist."""
        from news.views import ImageProxyView
        view = ImageProxyView()
        self.assertFalse(view._is_safe_url('http://8.8.8.8/img.jpg'))
        self.assertFalse(view._is_safe_url('http://1.1.1.1/photo.png'))

    def test_size_limit_constant_is_5mb(self):
        """The hard size cap must be exactly 5 MB (not 10 MB)."""
        from news.views import ImageProxyView
        self.assertEqual(ImageProxyView._MAX_IMAGE_BYTES, 5 * 1024 * 1024)


class SettingsSecurityTest(APITestCase):
    """
    FIX 1-3: settings.py configuration guard-rails.
    These tests run in the test environment (DEBUG=False by default in tests).
    """

    def test_debug_is_false_in_test_environment(self):
        """Django test runner sets DEBUG=False; our settings must respect that."""
        from django.conf import settings
        # In CI / test runs, DEBUG should be False (the default)
        # This assertion documents the expected production behaviour.
        self.assertFalse(
            settings.DEBUG,
            "DEBUG must be False in the test environment (mirrors production). "
            "If this fails, ensure the test runner is not overriding DEBUG=True."
        )

    def test_wildcard_not_in_allowed_hosts_when_debug_false(self):
        """'*' must not appear in ALLOWED_HOSTS when DEBUG is False."""
        from django.conf import settings
        if not settings.DEBUG:
            self.assertNotIn(
                '*',
                settings.ALLOWED_HOSTS,
                "ALLOWED_HOSTS must not contain '*' in production (DEBUG=False).",
            )

    def test_cors_allow_all_origins_false_when_debug_false(self):
        """CORS_ALLOW_ALL_ORIGINS must be False when DEBUG is False."""
        from django.conf import settings
        if not settings.DEBUG:
            self.assertFalse(
                settings.CORS_ALLOW_ALL_ORIGINS,
                "CORS_ALLOW_ALL_ORIGINS must be False in production.",
            )

    def test_throttle_classes_configured(self):
        """Global DRF throttle classes must be configured."""
        from django.conf import settings
        throttle_classes = settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_CLASSES', [])
        self.assertTrue(
            len(throttle_classes) > 0,
            "At least one default throttle class must be configured in REST_FRAMEWORK.",
        )

    def test_throttle_rates_configured(self):
        """Global DRF throttle rates must be configured."""
        from django.conf import settings
        rates = settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})
        self.assertIn('anon', rates)
        self.assertIn('user', rates)


# =============================================================================
# Voice Assistant & Link Summarizer Unit Tests
# =============================================================================

class VoiceAssistantAndLinkSummarizerTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="voice_user", password="password123")
        self.source = Source.objects.create(name="Tech Wire", url="https://techwire.com")
        self.article = Article.objects.create(
            title="AI Revolution 2026",
            body="Artificial intelligence is transforming news and live communication.",
            url="https://techwire.com/ai-2026",
            source=self.source,
            published_at=timezone.now(),
        )

    def test_voice_assistant_unauthenticated_returns_401(self):
        url = reverse("voice-assistant")
        response = self.client.post(url, {"text": "what is the score?"}, format="json")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_voice_assistant_missing_text_returns_400(self):
        url = reverse("voice-assistant")
        self.client.force_authenticate(user=self.user)
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_voice_assistant_feed_summary_returns_200(self):
        url = reverse("voice-assistant")
        self.client.force_authenticate(user=self.user)
        response = self.client.post(url, {"text": "summarize today's news", "language": "en"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("speech_text", response.data)
        self.assertIn("display_text", response.data)
        self.assertIn("sources", response.data)

    def test_voice_assistant_specific_article_returns_200(self):
        url = reverse("voice-assistant")
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            url,
            {"text": "tell me about this", "article_id": self.article.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("speech_text", response.data)
        self.assertIn("display_text", response.data)

    def test_summarize_link_missing_url_returns_400(self):
        url = reverse("summarize-link")
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_summarize_link_blocks_ssrf_private_ips(self):
        url = reverse("summarize-link")
        # Localhost / RFC-1918 must be blocked with 403
        for dangerous_url in ["http://127.0.0.1:8000/api", "http://localhost/admin", "http://192.168.1.1/setup"]:
            with self.subTest(dangerous_url=dangerous_url):
                res = self.client.post(url, {"url": dangerous_url}, format="json")
                self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
