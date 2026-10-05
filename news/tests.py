from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework.test import APITestCase
from rest_framework import status

from news.models import Article, Source, Genre, Region, ClarificationClaim, ClaimVote
from news.scoring import should_clarify

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

        self.claim.refresh_from_db()
        self.assertFalse(self.claim.is_active_badge)
        self.assertEqual(self.claim.article.clarify_status, Article.ClarifyStatus.NONE)

    def test_established_accounts_activate_badge_and_article_status(self):
        """Diverse established accounts agreeing triggers badge and updates article status."""
        for i in range(3):
            voter = User.objects.create_user(username=f"veteran_{i}", karma=25)
            ClaimVote.objects.create(claim=self.claim, user=voter, value=1)

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