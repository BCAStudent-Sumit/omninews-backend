from datetime import datetime
from time import mktime
import feedparser
from django.core.management.base import BaseCommand
from django.utils import timezone
from news.models import Article, Source, Genre, Region

# Multi-source feed registry (Global, National, and Regional Languages)
FEEDS_CONFIG = [
    {
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "source_name": "BBC News",
        "source_url": "https://www.bbc.com/news",
        "genre_name": "Technology",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },
    {
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "source_name": "BBC World",
        "source_url": "https://www.bbc.com/news/world",
        "genre_name": "World",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },
    {
        "url": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
        "source_name": "Google News India (EN)",
        "source_url": "https://news.google.com/?hl=en-IN",
        "genre_name": "National",
        "region_code": "IN",
        "region_name": "India",
    },
    {
        "url": "https://news.google.com/rss?hl=hi&gl=IN&ceid=IN:hi",
        "source_name": "Google News (Hindi)",
        "source_url": "https://news.google.com/?hl=hi-IN",
        "genre_name": "National",
        "region_code": "IN",
        "region_name": "India",
    },
    {
        "url": "https://news.google.com/rss?hl=bn&gl=IN&ceid=IN:bn",
        "source_name": "Google News (Bengali)",
        "source_url": "https://news.google.com/?hl=bn-IN",
        "genre_name": "Regional",
        "region_code": "WB",
        "region_name": "West Bengal",
    },
]

class Command(BaseCommand):
    help = "Fetch articles from RSS feeds and store them in the database"

    def handle(self, *args, **options):
        total_created = 0
        total_skipped = 0

        for config in FEEDS_CONFIG:
            feed_url = config["url"]
            self.stdout.write(f"Fetching RSS feed from: {config['source_name']} ({feed_url})")

            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                self.stderr.write(self.style.WARNING(f"Could not parse {config['source_name']}: {feed.bozo_exception}"))
                continue

            source, _ = Source.objects.get_or_create(
                url=config["source_url"],
                defaults={"name": config["source_name"]}
            )
            genre, _ = Genre.objects.get_or_create(name=config["genre_name"])
            region, _ = Region.objects.get_or_create(
                code=config["region_code"],
                defaults={"name": config["region_name"]}
            )

            created_count = 0
            skipped_count = 0

            for entry in feed.entries:
                article_url = getattr(entry, "link", None)
                if not article_url:
                    continue

                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published_dt = datetime.fromtimestamp(mktime(entry.published_parsed))
                    published_at = timezone.make_aware(published_dt, timezone.get_current_timezone())
                else:
                    published_at = timezone.now()

                _, created = Article.objects.get_or_create(
                    url=article_url,
                    defaults={
                        "title": getattr(entry, "title", "No Title"),
                        "body": getattr(entry, "summary", ""),
                        "source": source,
                        "genre": genre,
                        "region": region,
                        "published_at": published_at,
                    }
                )

                if created:
                    created_count += 1
                else:
                    skipped_count += 1

            total_created += created_count
            total_skipped += skipped_count
            self.stdout.write(f" -> {config['source_name']}: {created_count} added, {skipped_count} skipped.")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nTotal Ingestion Finished: {total_created} articles added, {total_skipped} skipped."
            )
        )