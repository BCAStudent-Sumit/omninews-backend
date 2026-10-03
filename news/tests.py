from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from news.models import Article, Source, Genre, Region

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
        # Article 1: Older, but matches both Genre (Tech: +2) and Region (Asia: +1) => Score 3
        self.top_match_article = Article.objects.create(
            title="Top Match Tech Asia",
            url="https://example.com/1",
            body="Content 1",
            source=self.source,
            genre=self.genre_tech,
            region=self.region_asia,
            published_at=now - timedelta(days=2)
        )

        # Article 2: Brand new, but no genre or region match for our user => Score 0
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