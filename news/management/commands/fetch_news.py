import re
import urllib.request
from datetime import datetime
from time import mktime
import feedparser
from django.core.management.base import BaseCommand
from django.utils import timezone
from news.models import Article, Source, Genre, Region

# Premier Global, National, and Regional Multi-Source Feed Registry
FEEDS_CONFIG = [
    # --- 1. BBC News (Global Broadcaster) ---
    {
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "source_name": "BBC News",
        "source_url": "https://www.bbc.com/news/technology",
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
        "url": "https://feeds.bbci.co.uk/sport/rss.xml",
        "source_name": "BBC Sport",
        "source_url": "https://www.bbc.com/sport",
        "genre_name": "Sports",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },

    # --- 2. The Hindu (Premier Indian Broadcaster - 1200px Crystal-Clear Photography) ---
    {
        "url": "https://www.thehindu.com/news/national/feeder/default.rss",
        "source_name": "The Hindu",
        "source_url": "https://www.thehindu.com/news/national/",
        "genre_name": "National",
        "region_code": "IN",
        "region_name": "India",
    },
    {
        "url": "https://www.thehindu.com/news/international/feeder/default.rss",
        "source_name": "The Hindu",
        "source_url": "https://www.thehindu.com/news/international/",
        "genre_name": "World",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },
    {
        "url": "https://www.thehindu.com/sci-tech/technology/feeder/default.rss",
        "source_name": "The Hindu",
        "source_url": "https://www.thehindu.com/sci-tech/technology/",
        "genre_name": "Technology",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },
    {
        "url": "https://www.thehindu.com/sport/feeder/default.rss",
        "source_name": "The Hindu",
        "source_url": "https://www.thehindu.com/sport/",
        "genre_name": "Sports",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },

    # --- 3. Times of India (TOI - Largest Indian Media Daily) ---
    {
        "url": "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms",
        "source_name": "Times of India",
        "source_url": "https://timesofindia.indiatimes.com/india",
        "genre_name": "National",
        "region_code": "IN",
        "region_name": "India",
    },
    {
        "url": "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",
        "source_name": "Times of India",
        "source_url": "https://timesofindia.indiatimes.com/world",
        "genre_name": "World",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },
    {
        "url": "https://timesofindia.indiatimes.com/rssfeeds/66949542.cms",
        "source_name": "Times of India",
        "source_url": "https://timesofindia.indiatimes.com/technology",
        "genre_name": "Technology",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },
    {
        "url": "https://timesofindia.indiatimes.com/rssfeeds/4719148.cms",
        "source_name": "Times of India",
        "source_url": "https://timesofindia.indiatimes.com/sports",
        "genre_name": "Sports",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },

    # --- 4. CNN International (Leading Global 24/7 Channel) ---
    {
        "url": "http://rss.cnn.com/rss/edition.rss",
        "source_name": "CNN",
        "source_url": "https://edition.cnn.com",
        "genre_name": "World",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },
    {
        "url": "http://rss.cnn.com/rss/edition_technology.rss",
        "source_name": "CNN",
        "source_url": "https://edition.cnn.com/business/tech",
        "genre_name": "Technology",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },
    {
        "url": "http://rss.cnn.com/rss/edition_sport.rss",
        "source_name": "CNN",
        "source_url": "https://edition.cnn.com/sport",
        "genre_name": "Sports",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },

    # --- 5. The Guardian (World-Class Editorial Photography & Investigative Journalism) ---
    {
        "url": "https://www.theguardian.com/world/rss",
        "source_name": "The Guardian",
        "source_url": "https://www.theguardian.com/world",
        "genre_name": "World",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },
    {
        "url": "https://www.theguardian.com/technology/rss",
        "source_name": "The Guardian",
        "source_url": "https://www.theguardian.com/technology",
        "genre_name": "Technology",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },
    {
        "url": "https://www.theguardian.com/sport/rss",
        "source_name": "The Guardian",
        "source_url": "https://www.theguardian.com/sport",
        "genre_name": "Sports",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },

    # --- 6. Hindustan Times (National & Breaking - 1600x900 HD Imagery) ---
    {
        "url": "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",
        "source_name": "Hindustan Times",
        "source_url": "https://www.hindustantimes.com/india-news",
        "genre_name": "National",
        "region_code": "IN",
        "region_name": "India",
    },
    {
        "url": "https://www.hindustantimes.com/feeds/rss/world-news/rssfeed.xml",
        "source_name": "Hindustan Times",
        "source_url": "https://www.hindustantimes.com/world-news",
        "genre_name": "World",
        "region_code": "GLOBAL",
        "region_name": "Global",
    },

    # --- 7. NDTV (Indian 24x7 News Channel) ---
    {
        "url": "https://feeds.feedburner.com/ndtvnews-top-stories",
        "source_name": "NDTV",
        "source_url": "https://www.ndtv.com",
        "genre_name": "National",
        "region_code": "IN",
        "region_name": "India",
    },

    # --- 8. Regional & Multilingual Google News Feeds ---
    {
        "url": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
        "source_name": "Google News India",
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
        "language": "bn",
    },

    # --- 9. Artificial Intelligence (Dedicated Tech, LLMs, Machine Learning & Robotics) ---
    {
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "source_name": "TechCrunch AI",
        "source_url": "https://techcrunch.com/category/artificial-intelligence/",
        "genre_name": "Artificial Intelligence",
        "region_code": "GLOBAL",
        "region_name": "Global",
        "language": "en",
    },
    {
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "source_name": "The Verge AI",
        "source_url": "https://www.theverge.com/ai-artificial-intelligence",
        "genre_name": "Artificial Intelligence",
        "region_code": "GLOBAL",
        "region_name": "Global",
        "language": "en",
    },
    {
        "url": "https://venturebeat.com/category/ai/feed/",
        "source_name": "VentureBeat AI",
        "source_url": "https://venturebeat.com/category/ai/",
        "genre_name": "Artificial Intelligence",
        "region_code": "GLOBAL",
        "region_name": "Global",
        "language": "en",
    },
    {
        "url": "https://news.google.com/rss/search?q=Artificial+Intelligence+OpenAI+Google+Gemini+Anthropic&hl=en-US&gl=US&ceid=US:en",
        "source_name": "Google AI Wire",
        "source_url": "https://news.google.com",
        "genre_name": "Artificial Intelligence",
        "region_code": "GLOBAL",
        "region_name": "Global",
        "language": "en",
    },
    {
        "url": "https://news.google.com/rss/search?q=Artificial+Intelligence+India+startups&hl=en-IN&gl=IN&ceid=IN:en",
        "source_name": "Google AI India",
        "source_url": "https://news.google.com",
        "genre_name": "Artificial Intelligence",
        "region_code": "IN",
        "region_name": "India",
        "language": "en",
    },
    {
        "url": "https://news.google.com/rss/search?q=%E0%A6%8F%E0%A6%86%E0%A6%87+OR+%E0%A6%95%E0%A7%83%E0%A6%A4%E0%A7%8D%E0%A6%B0%E0%A6%BF%E0%A6%AE+%E0%A6%AE%E0%A7%87%E0%A6%A7%E0%A6%BE&hl=bn&gl=IN&ceid=IN:bn",
        "source_name": "Google AI (Bengali)",
        "source_url": "https://news.google.com",
        "genre_name": "Artificial Intelligence",
        "region_code": "WB",
        "region_name": "West Bengal",
        "language": "bn",
    },
]


def fetch_og_image_from_page(url):
    """
    Fetches the actual newsroom photograph from the article page <meta property="og:image">
    when the RSS feed does not provide an enclosure or thumbnail.
    """
    if not url or "news.google.com" in url:
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            html = resp.read(45000).decode('utf-8', errors='ignore')
            m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
            if not m:
                m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']', html, re.I)
            if m:
                img = m.group(1).strip()
                bad_markers = ["1x1", "pixel", "beacon", "logo", "placeholder", "default_img", "/theme/images/", "og-image.png", "default_share", "default_thumb", "generic_avatar"]
                if not any(bad in img.lower() for bad in bad_markers):
                    return img
    except Exception:
        pass
    return None


def extract_high_res_image(entry, article_url=None):
    """
    Intelligently extracts and optimizes high-resolution photography from various news feeds.
    Checks media_content, enclosures, media_thumbnail, HTML descriptions, and fallback publisher og:image.
    """
    image_url = None

    # 0. Direct news_image attribute (Bing News RSS and high-res syndication wires)
    if hasattr(entry, "news_image") and entry.news_image:
        image_url = str(entry.news_image).strip()

    # 1. Media content attribute (The Hindu, CNN, The Guardian, etc.)
    if not image_url and hasattr(entry, "media_content") and entry.media_content:
        candidates = []
        for mc in entry.media_content:
            if isinstance(mc, dict) and mc.get("url"):
                url = mc.get("url")
                if not any(bad in url.lower() for bad in ["1x1", "pixel", "beacon", "logo", "c.ndtvimg.com"]):
                    try:
                        width = int(mc.get("width", 0) or 0)
                    except (ValueError, TypeError):
                        width = 0
                    candidates.append((width, url))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            image_url = candidates[0][1]

    # 2. Enclosures attribute (Times of India, NDTV, podcasts/photo attachments)
    if not image_url and hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if isinstance(enc, dict):
                enc_type = enc.get("type", "").lower()
                href = enc.get("href", "")
                if any(t in enc_type for t in ["image", "jpeg", "jpg", "png", "webp"]) or any(href.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    image_url = href
                    break

    # 3. Media thumbnail attribute
    if not image_url and hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        for thumb in entry.media_thumbnail:
            if isinstance(thumb, dict) and thumb.get("url"):
                image_url = thumb.get("url")
                break

    # 4. Embedded <img> in summary or content HTML
    if not image_url:
        for field in ["summary", "description", "content"]:
            val = getattr(entry, field, "")
            if isinstance(val, list) and val and isinstance(val[0], dict):
                val = val[0].get("value", "")
            if isinstance(val, str) and "<img" in val:
                m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', val)
                if m:
                    candidate = m.group(1)
                    if not any(bad in candidate.lower() for bad in ["1x1", "pixel", "beacon", "feedburner", "icon"]):
                        image_url = candidate
                        break

    # 5. Direct publisher webpage extraction fallback (for articles lacking RSS enclosures)
    if not image_url and article_url:
        image_url = fetch_og_image_from_page(article_url)

    # 6. Quality & Resolution Enhancer for Premier News Networks
    if image_url:
        # BBC: Upgrade thumbnail from 240/320px to 800/1024px crystal-clear HD
        if "ichef.bbci.co.uk" in image_url:
            image_url = image_url.replace("/240/", "/800/").replace("/320/", "/1024/")

        # CNN: Upgrade preview thumbnails to large 16:9 banner
        if "cdn.cnn.com" in image_url and "-small-" in image_url:
            image_url = image_url.replace("-small-", "-large-")

    return image_url


class Command(BaseCommand):
    help = "Fetch articles from multiple premier free news APIs with high-resolution imagery"

    def handle(self, *args, **options):
        total_created = 0
        total_skipped = 0

        self.stdout.write("========================================================")
        self.stdout.write(" Starting OmniNews Multi-Source Ingestion Pipeline")
        self.stdout.write(f" Querying {len(FEEDS_CONFIG)} premier news channel feeds...")
        self.stdout.write("========================================================")

        for config in FEEDS_CONFIG:
            feed_url = config["url"]
            source_name = config["source_name"]

            try:
                feed = feedparser.parse(feed_url)
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"Could not connect to {source_name}: {e}"))
                continue

            if feed.bozo and not feed.entries:
                self.stderr.write(self.style.WARNING(f"Could not parse {source_name}: {feed.bozo_exception}"))
                continue

            source, _ = Source.objects.get_or_create(
                url=config["source_url"],
                defaults={"name": source_name}
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

                # Extract and boost high-resolution image
                image_url = extract_high_res_image(entry, article_url=article_url)

                title_val = getattr(entry, "title", "No Title")
                lang_code = config.get("language")
                if not lang_code:
                    if re.search(r'[\u0980-\u09ff]', title_val):
                        lang_code = "bn"
                    elif re.search(r'[\u0900-\u097f]', title_val):
                        lang_code = "hi"
                    else:
                        lang_code = "en"

                article, created = Article.objects.update_or_create(
                    url=article_url,
                    defaults={
                        "title": title_val,
                        "body": getattr(entry, "summary", ""),
                        "source": source,
                        "genre": genre,
                        "region": region,
                        "language": lang_code,
                        "published_at": published_at,
                        "image_url": image_url,
                    }
                )

                if created:
                    created_count += 1
                else:
                    skipped_count += 1

            total_created += created_count
            total_skipped += skipped_count
            self.stdout.write(f" -> {source_name} [{config['genre_name']}]: {created_count} added, {skipped_count} updated/skipped.")

        # Dynamically auto-fetch news for any user-added or custom genres in the database!
        try:
            from news.views import fetch_genre_news
            known_feed_genres = {c["genre_name"].lower() for c in FEEDS_CONFIG}
            for g in Genre.objects.all():
                if g.name.lower() not in known_feed_genres:
                    c = fetch_genre_news(g, max_entries=25)
                    self.stdout.write(f" -> [Auto-Discovered Genre] {g.name}: {c} synced.")
        except Exception as e:
            self.stderr.write(f"Custom genres sync warning: {e}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nFinished Multi-Source Ingestion: {total_created} new articles added, {total_skipped} synced."
            )
        )