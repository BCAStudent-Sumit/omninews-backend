import feedparser
from datetime import datetime
from time import mktime
from django.core.management.base import BaseCommand
from django.utils import timezone
from news.models import Article, Source, Genre, Region

class Command(BaseCommand):
    help = "Fetch articles from RSS feeds and store them in the database"

    def handle(self, *args, **options):
        # 1. RSS feed configuration
        feed_url = "https://feeds.bbci.co.uk/news/technology/rss.xml"
        self.stdout.write(f"Fetching RSS feed from: {feed_url}")

        feed = feedparser.parse(feed_url)

        if feed.bozo:
            self.stderr.write(self.style.ERROR(f"Error parsing feed: {feed.bozo_exception}"))
            return

        # 2. Get or create associated Source, Genre, and Region
        source, _ = Source.objects.get_or_create(
            name="BBC News",
            defaults={"url": "https://www.bbc.com/news"}
        )
        tech_genre, _ = Genre.objects.get_or_create(name="Technology")
        europe_region, _ = Region.objects.get_or_create(code="EU", defaults={"name": "Europe"})

        created_count = 0
        skipped_count = 0

        # 3. Iterate over entries
        for entry in feed.entries:
            article_url = getattr(entry, "link", None)
            if not article_url:
                continue

            # Parse published date safely
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_dt = datetime.fromtimestamp(mktime(entry.published_parsed))
                published_at = timezone.make_aware(published_dt, timezone.get_current_timezone())
            else:
                published_at = timezone.now()

            # Prevent duplicates via unique URL
            article, created = Article.objects.get_or_create(
                url=article_url,
                defaults={
                    "title": getattr(entry, "title", "No Title"),
                    "body": getattr(entry, "summary", ""),
                    "source": source,
                    "genre": tech_genre,
                    "region": europe_region,
                    "published_at": published_at,
                }
            )

            if created:
                created_count += 1
            else:
                skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Ingestion completed: {created_count} articles added, {skipped_count} skipped (already exist)."
            )
        )