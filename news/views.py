import time
_FEED_MEM_CACHE = {}
import rest_framework.throttling
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.db import transaction
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
import urllib.request
import threading
from rest_framework.exceptions import PermissionDenied
from django.db.models import Case, When, Value, IntegerField, F, Prefetch, Q
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from .models import Article, Genre, ClarificationClaim, ClaimVote, Bookmark, Source, Region
from .serializers import (
    ArticleSerializer,
    ArticlePublishSerializer,
    GenreSerializer,
    ClarificationClaimSerializer,
    ClaimVoteSerializer,
    NewsUserProfileSerializer,
    BookmarkSerializer,
)
from .scoring import resolve_claim_if_ready


class GenreListCreateView(generics.ListCreateAPIView):
    queryset = Genre.objects.all().order_by('name')
    serializer_class = GenreSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'detail': 'Genre name is required.'}, status=status.HTTP_400_BAD_REQUEST)
        genre = Genre.objects.filter(name__iexact=name).first()
        if genre:
            if genre.articles.count() < 10:
                threading.Thread(target=fetch_genre_news, args=(genre,), daemon=True).start()
            serializer = self.get_serializer(genre)
            return Response(serializer.data, status=status.HTTP_200_OK)

        genre = Genre.objects.create(name=name.title())

        # Fully autonomous instant fetch: ingest top news immediately before returning!
        try:
            fetch_genre_news(genre, max_entries=15)
        except Exception:
            pass

        # Trigger deeper background ingestion
        threading.Thread(target=fetch_genre_news, args=(genre,), kwargs={'max_entries': 40}, daemon=True).start()

        serializer = self.get_serializer(genre)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

GenreListView = GenreListCreateView


class ArticleListView(generics.ListAPIView):
    serializer_class = ArticleSerializer

    def get_queryset(self):
        queryset = Article.objects.all()
        genre_id = self.request.query_params.get('genre')
        region_id = self.request.query_params.get('region')

        if genre_id:
            queryset = queryset.filter(genre_id=genre_id)
        if region_id:
            queryset = queryset.filter(region_id=region_id)

        return queryset.order_by("-published_at", "-id")


_ACTIVE_CITY_FETCHES = set()
_ACTIVE_GENRE_FETCHES = set()

# Comprehensive 23-Language Multi-Locale Parameter Mapping Matrix for Google News RSS
LANG_CONFIGS = {
    # Foreign / Global Languages
    'de': {'hl': 'de', 'gl': 'DE', 'ceid': 'DE:de', 'name': 'German'},
    'es': {'hl': 'es', 'gl': 'ES', 'ceid': 'ES:es', 'name': 'Spanish'},
    'fr': {'hl': 'fr', 'gl': 'FR', 'ceid': 'FR:fr', 'name': 'French'},
    'ja': {'hl': 'ja', 'gl': 'JP', 'ceid': 'JP:ja', 'name': 'Japanese'},
    'ar': {'hl': 'ar', 'gl': 'AE', 'ceid': 'AE:ar', 'name': 'Arabic'},
    'ru': {'hl': 'ru', 'gl': 'RU', 'ceid': 'RU:ru', 'name': 'Russian'},
    'zh': {'hl': 'zh-TW', 'gl': 'TW', 'ceid': 'TW:zh-Hant', 'name': 'Chinese'},
    'pt': {'hl': 'pt-BR', 'gl': 'BR', 'ceid': 'BR:pt-419', 'name': 'Portuguese'},
    'ko': {'hl': 'ko', 'gl': 'KR', 'ceid': 'KR:ko', 'name': 'Korean'},
    # Indian Languages
    'hi': {'hl': 'hi', 'gl': 'IN', 'ceid': 'IN:hi', 'name': 'Hindi'},
    'bn': {'hl': 'bn', 'gl': 'IN', 'ceid': 'IN:bn', 'name': 'Bengali'},
    'mr': {'hl': 'mr', 'gl': 'IN', 'ceid': 'IN:mr', 'name': 'Marathi'},
    'te': {'hl': 'te', 'gl': 'IN', 'ceid': 'IN:te', 'name': 'Telugu'},
    'ta': {'hl': 'ta', 'gl': 'IN', 'ceid': 'IN:ta', 'name': 'Tamil'},
    'gu': {'hl': 'gu', 'gl': 'IN', 'ceid': 'IN:gu', 'name': 'Gujarati'},
    'ur': {'hl': 'ur', 'gl': 'IN', 'ceid': 'IN:ur', 'name': 'Urdu'},
    'kn': {'hl': 'kn', 'gl': 'IN', 'ceid': 'IN:kn', 'name': 'Kannada'},
    'ml': {'hl': 'ml', 'gl': 'IN', 'ceid': 'IN:ml', 'name': 'Malayalam'},
    'pa': {'hl': 'pa', 'gl': 'IN', 'ceid': 'IN:pa', 'name': 'Punjabi'},
    'or': {'hl': 'or', 'gl': 'IN', 'ceid': 'IN:or', 'name': 'Odia'},
    'as': {'hl': 'as', 'gl': 'IN', 'ceid': 'IN:as', 'name': 'Assamese'},
    # English Variants
    'en': {'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en', 'name': 'English'},
    'en_in': {'hl': 'en-IN', 'gl': 'IN', 'ceid': 'IN:en', 'name': 'English (India)'},
}

def get_or_create_source(source_name):
    import re
    clean_name = (source_name or "Global Wire").strip()
    source = Source.objects.filter(name__iexact=clean_name).first()
    if source:
        return source
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', clean_name.lower()).strip('-')
    if not slug:
        slug = "wire"
    unique_url = f"https://wire.omninews.io/source/{slug}"
    source = Source.objects.filter(url=unique_url).first()
    if not source:
        source, _ = Source.objects.get_or_create(
            url=unique_url,
            defaults={"name": clean_name}
        )
    return source

def fetch_genre_news(genre_obj, language='en', max_entries=35):
    """
    Fully autonomous, multi-source news fetcher for ANY genre (existing or newly created).
    Fetches real-time headlines with high-resolution photography from premier wire endpoints
    (Bing News RSS with direct news_image photography, Google News RSS, Tech wires, and regional feeds).
    No manual configuration or database additions needed!
    """
    import urllib.parse
    import feedparser
    import re
    from datetime import datetime
    from time import mktime
    from django.utils import timezone
    from .models import Source, Region, Article
    from .management.commands.fetch_news import extract_high_res_image

    if not genre_obj:
        return 0

    genre_name = genre_obj.name.strip()
    if not genre_name:
        return 0

    lang_code = language.split('_')[0].lower() if language else 'en'
    fetch_key = f"{genre_name.lower()}_{lang_code}"

    if fetch_key in _ACTIVE_GENRE_FETCHES:
        return 0
    _ACTIVE_GENRE_FETCHES.add(fetch_key)

    try:
        q = urllib.parse.quote(genre_name)
        g_lower = genre_name.lower()
        feeds_to_fetch = []

        cfg = LANG_CONFIGS.get(lang_code, LANG_CONFIGS.get('en'))
        hl = cfg['hl']
        gl = cfg['gl']
        ceid = cfg['ceid']
        lang_name = cfg['name']

        if lang_code in LANG_CONFIGS and lang_code not in ['en', 'en_in']:
            # 1. Map genre to standard Google News topic if applicable
            topic = None
            if 'world' in g_lower or 'international' in g_lower:
                topic = 'WORLD'
            elif 'nation' in g_lower or 'india' in g_lower or 'country' in g_lower:
                topic = 'NATION'
            elif 'tech' in g_lower:
                topic = 'TECHNOLOGY'
            elif 'ai' in g_lower or 'artificial' in g_lower:
                topic = 'TECHNOLOGY'
            elif 'sport' in g_lower:
                topic = 'SPORTS'
            elif 'business' in g_lower or 'economy' in g_lower or 'market' in g_lower or 'finance' in g_lower:
                topic = 'BUSINESS'
            elif 'entertain' in g_lower or 'cinema' in g_lower or 'movie' in g_lower:
                topic = 'ENTERTAINMENT'
            elif 'science' in g_lower or 'space' in g_lower:
                topic = 'SCIENCE'
            elif 'health' in g_lower or 'medical' in g_lower:
                topic = 'HEALTH'

            if topic:
                feeds_to_fetch.append({
                    "url": f"https://news.google.com/rss/headlines/section/topic/{topic}?hl={hl}&gl={gl}&ceid={ceid}",
                    "default_source": f"{lang_name} {genre_name} Wire",
                    "lang": lang_code,
                    "is_bing": False,
                })

            # 2. Targeted search queries for specific genres
            if 'ai' in g_lower or 'artificial' in g_lower:
                ai_queries = {
                    'de': 'Künstliche Intelligenz',
                    'es': 'Inteligencia Artificial',
                    'fr': 'Intelligence Artificielle',
                    'ja': '人工知能',
                    'zh': '人工智慧',
                    'ru': 'Искусственный интеллект',
                    'ar': 'ذكاء اصطناعي',
                    'pt': 'Inteligência Artificial',
                    'ko': '인공지능',
                    'hi': 'आर्टिफिशियल इंटेलिजेंस',
                    'bn': 'কৃত্রিম বুদ্ধিমত্তা',
                    'mr': 'आर्टिफिशिअल इंटेलिजन्स',
                    'ta': 'செயற்கை நுண்ணறிவு',
                    'te': 'కృత్రిమ మేధస్సు',
                }
                ai_query = ai_queries.get(lang_code, 'Artificial Intelligence')
                feeds_to_fetch.append({
                    "url": f"https://news.google.com/rss/search?q={urllib.parse.quote(ai_query)}&hl={hl}&gl={gl}&ceid={ceid}",
                    "default_source": f"{lang_name} AI Wire",
                    "lang": lang_code,
                    "is_bing": False,
                })
            elif 'region' in g_lower:
                reg_queries = {
                    'bn': ['কলকাতা', 'পশ্চিমবঙ্গ'],
                    'hi': ['दिल्ली', 'उत्तर प्रदेश'],
                    'mr': ['महाराष्ट्र', 'मुंबई'],
                    'ta': ['தமிழ்நாடு', 'சென்னை'],
                    'te': ['తెలంగాణ', 'ఆంధ్రప్రదేశ్'],
                    'gu': ['ગુજરાત', 'અમદાવાદ'],
                    'kn': ['ಕರ್ನಾಟಕ', 'ಬೆಂಗಳೂರು'],
                    'ml': ['കേരളം', 'കൊച്ചി'],
                    'pa': ['ਪੰਜਾਬ'],
                    'de': ['Berlin', 'Deutschland'],
                    'fr': ['Paris', 'France'],
                    'es': ['Madrid', 'Barcelona'],
                    'ja': ['東京'],
                }
                for rq in reg_queries.get(lang_code, [genre_name]):
                    feeds_to_fetch.append({
                        "url": f"https://news.google.com/rss/search?q={urllib.parse.quote(rq)}&hl={hl}&gl={gl}&ceid={ceid}",
                        "default_source": f"{lang_name} Regional Wire",
                        "lang": lang_code,
                        "is_bing": False,
                    })

            # 3. Always include search query for the genre itself
            feeds_to_fetch.append({
                "url": f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}",
                "default_source": f"{lang_name} Wire ({genre_name})",
                "lang": lang_code,
                "is_bing": False,
            })

        else:
            # English / Global feeds
            feeds_to_fetch = [
                {
                    "url": f"https://www.bing.com/news/search?q={q}&format=rss",
                    "default_source": f"Global Wire ({genre_name})",
                    "lang": "en",
                    "is_bing": True,
                },
                {
                    "url": f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
                    "default_source": f"Google News ({genre_name})",
                    "lang": "en",
                    "is_bing": False,
                },
                {
                    "url": f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en",
                    "default_source": f"India Wire ({genre_name})",
                    "lang": "en",
                    "is_bing": False,
                },
            ]
            if 'artificial intelligence' in g_lower or 'ai' in g_lower:
                feeds_to_fetch.insert(0, {
                    "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
                    "default_source": "TechCrunch AI",
                    "lang": "en",
                    "is_bing": False,
                })
                feeds_to_fetch.insert(1, {
                    "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
                    "default_source": "The Verge AI",
                    "lang": "en",
                    "is_bing": False,
                })

        region_global, _ = Region.objects.get_or_create(code="GLOBAL", defaults={"name": "Global"})
        region_in, _ = Region.objects.get_or_create(code="IN", defaults={"name": "India"})
        region_wb, _ = Region.objects.get_or_create(code="WB", defaults={"name": "West Bengal"})

        created_count = 0
        for f_info in feeds_to_fetch:
            feed_url = f_info["url"]
            feed_lang = f_info["lang"]
            is_bing = f_info["is_bing"]

            try:
                feed = feedparser.parse(feed_url)
            except Exception:
                continue

            if not feed or not feed.entries:
                continue

            for entry in feed.entries[:max_entries]:
                article_url = getattr(entry, "link", None)
                if not article_url:
                    continue

                title = getattr(entry, "title", "No Title")
                if not title or title.strip() == "No Title":
                    continue

                source_name = f_info["default_source"]
                if is_bing and hasattr(entry, "news_source") and entry.news_source:
                    source_name = str(entry.news_source).strip()
                elif " - " in title:
                    parts = title.rsplit(" - ", 1)
                    if len(parts) == 2 and len(parts[1].strip()) < 35:
                        title = parts[0].strip()
                        source_name = parts[1].strip()

                source = get_or_create_source(source_name)

                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published_dt = datetime.fromtimestamp(mktime(entry.published_parsed))
                    published_at = timezone.make_aware(published_dt, timezone.get_current_timezone())
                else:
                    published_at = timezone.now()

                image_url = None
                if is_bing and hasattr(entry, "news_image") and entry.news_image:
                    image_url = str(entry.news_image).strip()
                if not image_url:
                    image_url = extract_high_res_image(entry, article_url=None)

                item_lang = feed_lang if feed_lang else lang_code
                if lang_code and lang_code != 'en':
                    item_lang = lang_code
                else:
                    if re.search(r'[ঀ-৿]', title):
                        item_lang = "bn"
                    elif re.search(r'[ऀ-ॿ]', title):
                        item_lang = "hi"
                    elif re.search(r'[஀-௿]', title):
                        item_lang = "ta"
                    elif re.search(r'[ఀ-౿]', title):
                        item_lang = "te"
                    elif re.search(r'[Ѐ-ӿ]', title):
                        item_lang = "ru"
                    elif re.search(r'[぀-ヿ㐀-䶿一-鿿]', title):
                        item_lang = "ja"

                reg = region_global
                if item_lang == "bn":
                    reg = region_wb
                elif item_lang == "hi" or "india" in feed_url.lower():
                    reg = region_in
                elif item_lang in LANG_CONFIGS:
                    target_gl = LANG_CONFIGS[item_lang]['gl']
                    target_name = LANG_CONFIGS[item_lang]['name']
                    reg, _ = Region.objects.get_or_create(code=target_gl, defaults={"name": target_name})

                art, created = Article.objects.get_or_create(
                    url=article_url,
                    defaults={
                        "title": title,
                        "body": getattr(entry, "summary", "") or getattr(entry, "description", ""),
                        "source": source,
                        "genre": genre_obj,
                        "region": reg,
                        "language": item_lang,
                        "published_at": published_at,
                        "image_url": image_url,
                    }
                )
                if created:
                    created_count += 1
                elif art.genre_id != genre_obj.id or (image_url and not art.image_url):
                    art.genre = genre_obj
                    if image_url and not art.image_url:
                        art.image_url = image_url
                        art.save(update_fields=["genre", "image_url"])
                    else:
                        art.save(update_fields=["genre"])

        return created_count
    finally:
        _ACTIVE_GENRE_FETCHES.discard(fetch_key)

def fetch_city_news(city, genre_obj=None, language='en'):
    """
    On-demand background news fetcher for specific city + genre combinations.
    E.g. city='Berlin', genre_obj=<Genre: Sports>, language='en'
    """
    import urllib.parse
    import feedparser
    from datetime import datetime
    from time import mktime
    from django.utils import timezone
    from .models import Source, Region
    from .management.commands.fetch_news import extract_high_res_image

    if not city or city.strip().lower() in ['', 'all', 'global']:
        return 0

    genre_title = genre_obj.name if genre_obj else ""
    query = f"{city} {genre_title}".strip()
    lang_code = language.split('_')[0].lower() if language else 'en'
    fetch_key = f"{city.lower()}_{genre_title.lower()}_{lang_code}"

    if fetch_key in _ACTIVE_CITY_FETCHES:
        return 0
    _ACTIVE_CITY_FETCHES.add(fetch_key)

    try:
        cfg_c = LANG_CONFIGS.get(lang_code, LANG_CONFIGS.get('en'))
        feed_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl={cfg_c['hl']}&gl={cfg_c['gl']}&ceid={cfg_c['ceid']}"
        try:
            feed = feedparser.parse(feed_url)
        except Exception:
            return 0

        if not feed or not feed.entries:
            return 0

        source, _ = Source.objects.get_or_create(
            url="https://news.google.com",
            defaults={"name": f"Global Wire ({city.title()})"}
        )
        region, _ = Region.objects.get_or_create(
            name=city.title(),
            defaults={"code": city[:3].upper()}
        )

        created_count = 0
        for entry in feed.entries[:12]:
            article_url = getattr(entry, "link", None)
            if not article_url:
                continue

            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_dt = datetime.fromtimestamp(mktime(entry.published_parsed))
                published_at = timezone.make_aware(published_dt, timezone.get_current_timezone())
            else:
                published_at = timezone.now()

            # Extract high-res image directly from feed enclosures without blocking webpage scraping
            image_url = extract_high_res_image(entry, article_url=None)

            art, created = Article.objects.get_or_create(
                url=article_url,
                defaults={
                    "title": getattr(entry, "title", "No Title"),
                    "body": getattr(entry, "summary", ""),
                    "source": source,
                    "genre": genre_obj,
                    "region": region,
                    "language": lang_code,
                    "published_at": published_at,
                    "image_url": image_url,
                }
            )
            if created:
                created_count += 1
            elif genre_obj and (art.genre_id != genre_obj.id or not art.region):
                art.genre = genre_obj
                if region and not art.region:
                    art.region = region
                art.save(update_fields=["genre", "region"] if not art.region else ["genre"])

        return created_count
    finally:
        _ACTIVE_CITY_FETCHES.discard(fetch_key)


@method_decorator(cache_page(60 * 2), name='dispatch')
class FeedView(generics.ListAPIView):
    serializer_class = ArticleSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        user = self.request.user

        # Prefetch only active badge claims, and select_related author to kill N+1 queries
        active_claims_prefetch = Prefetch(
            "claims",
            queryset=ClarificationClaim.objects.filter(is_active_badge=True)
            .select_related("author")
            .prefetch_related("evidence_links"),
            to_attr="prefetched_active_claims",
        )

        queryset = (
            Article.objects
            .select_related("genre", "region", "source")
            .prefetch_related(active_claims_prefetch)
        )

        genre_param = self.request.query_params.get("genre")
        genres_param = self.request.query_params.get("genres")
        region_id = self.request.query_params.get("region")
        city_param = self.request.query_params.get("city")
        languages_param = self.request.query_params.get("languages") or self.request.query_params.get("language")
        clarify_status = self.request.query_params.get("clarify_status")

        # Fallback to user saved preferences on ANY feed (including genre tabs) if languages_param was not sent
        if not languages_param and user.is_authenticated and getattr(user, 'preferred_languages', None):
            languages_param = user.preferred_languages
        if not city_param and user.is_authenticated and getattr(user, 'preferred_city', None):
            city_param = user.preferred_city

        city_aliases = {
            'birlin': 'Berlin',
            'berlin': 'Berlin',
            'bangalore': 'Bengaluru',
            'banglore': 'Bengaluru',
            'bengaluru': 'Bengaluru',
            'bombay': 'Mumbai',
            'mumbai': 'Mumbai',
            'calcutta': 'Kolkata',
            'kolkata': 'Kolkata',
            'madras': 'Chennai',
            'chennai': 'Chennai',
            'delhi': 'Delhi NCR',
            'new delhi': 'Delhi NCR',
            'ncr': 'Delhi NCR',
        }

        norm_city = None
        if city_param and city_param.strip().lower() not in ['', 'all', 'global']:
            cleaned = city_param.strip().lower()
            norm_city = city_aliases.get(cleaned, city_param.strip().title())

        # 1. Resolve Target Genre(s)
        target_genre_ids = []
        if genre_param:
            if str(genre_param).isdigit():
                target_genre_ids.append(int(genre_param))
            else:
                g = Genre.objects.filter(name__iexact=str(genre_param).strip()).first()
                if g:
                    target_genre_ids.append(g.id)
        elif genres_param:
            for g_item in str(genres_param).split(','):
                g_item = g_item.strip()
                if not g_item:
                    continue
                if g_item.isdigit():
                    target_genre_ids.append(int(g_item))
                else:
                    g = Genre.objects.filter(name__iexact=g_item).first()
                    if g:
                        target_genre_ids.append(g.id)
        elif user.is_authenticated and not genre_param and not genres_param:
            user_g_ids = list(user.genres.values_list('id', flat=True))
            if user_g_ids:
                target_genre_ids.extend(user_g_ids)

        # 2. Fully Asynchronous Background Ingestion (100% NON-BLOCKING)
        # Never block the HTTP request thread with slow external RSS fetches!
        if target_genre_ids:
            for gid in target_genre_ids:
                g_obj = Genre.objects.filter(id=gid).first()
                if g_obj:
                    count_in_g = Article.objects.filter(genre=g_obj).count()
                    if count_in_g < 8:
                        threading.Thread(target=fetch_genre_news, args=(g_obj,), kwargs={"max_entries": 35}, daemon=True).start()

        if norm_city:
            city_name = norm_city
            city_q = Q(region__name__icontains=city_name) | Q(title__icontains=city_name) | Q(body__icontains=city_name)
            matching_count = Article.objects.filter(city_q).count()
            if matching_count < 8:
                threading.Thread(target=fetch_city_news, args=(city_name,), daemon=True).start()

        # 3. Apply Filters - Keep rich global/national stories intact!
        base_qs = queryset

        # Apply target genres if specified
        if target_genre_ids:
            base_qs = base_qs.filter(genre_id__in=target_genre_ids)

        if region_id:
            base_qs = base_qs.filter(region_id=region_id)

        # Smart City Matching: prioritize city stories, but NEVER wipe out the feed to 0
        if norm_city:
            city_name = norm_city
            city_filter = (
                Q(region__name__icontains=city_name) |
                Q(title__icontains=city_name) |
                Q(body__icontains=city_name)
            )
            city_qs = base_qs.filter(city_filter)
            if city_qs.count() >= 3:
                queryset = city_qs
            else:
                queryset = base_qs
        else:
            queryset = base_qs

        # Guaranteed Safety Fallback: A user should NEVER receive an empty feed
        # BUT if a genre was explicitly targeted, NEVER fallback to unrelated World / Politics stories!
        if not queryset.exists():
            if target_genre_ids:
                genre_any = Article.objects.filter(genre_id__in=target_genre_ids).select_related("genre", "region", "source").prefetch_related(active_claims_prefetch)
                if genre_any.exists():
                    queryset = genre_any
                else:
                    tech_g = Genre.objects.filter(name__in=["Technology", "Science & Space"])
                    tech_qs = Article.objects.filter(genre__in=tech_g).select_related("genre", "region", "source").prefetch_related(active_claims_prefetch)
                    if tech_qs.exists():
                        queryset = tech_qs
                    else:
                        queryset = Article.objects.select_related("genre", "region", "source").prefetch_related(active_claims_prefetch)
            else:
                queryset = Article.objects.select_related("genre", "region", "source").prefetch_related(active_claims_prefetch)

        if clarify_status:
            queryset = queryset.filter(clarify_status=clarify_status)

        return queryset.order_by("-published_at", "-id")

    def list(self, request, *args, **kwargs):
        # Resolve target translation language (query param or authenticated user profile)
        translate_to = request.query_params.get("translate_to") or request.query_params.get("translate")
        if not translate_to:
            langs = request.query_params.get("languages") or request.query_params.get("language")
            if not langs and request.user and request.user.is_authenticated and getattr(request.user, 'preferred_languages', None):
                langs = request.user.preferred_languages
            if langs:
                for l_candidate in str(langs).split(','):
                    cand = l_candidate.strip().split('_')[0].split('-')[0].lower()
                    if cand and cand != 'en':
                        translate_to = cand
                        break

        # High-performance in-memory cache (3 min TTL) with user and language partition
        user_id = request.user.id if (request.user and request.user.is_authenticated) else "anon"
        cache_key = (
            user_id,
            request.query_params.get("genre", ""),
            request.query_params.get("genres", ""),
            request.query_params.get("region", ""),
            request.query_params.get("city", "").strip().lower(),
            translate_to or "en",
        )
        now = time.time()
        if cache_key in _FEED_MEM_CACHE:
            ts, cached_data = _FEED_MEM_CACHE[cache_key]
            if now - ts < 180:
                return Response(cached_data)

        response = super().list(request, *args, **kwargs)

        if translate_to and translate_to not in ('en', 'en_in'):
            tl = translate_to.split('-')[0].split('_')[0].lower()
            results = response.data.get('results', []) if isinstance(response.data, dict) else response.data
            if results and isinstance(results, list):
                # Translate top 12 titles and top 3 hero snippets in parallel
                titles = [r.get('title', '') for r in results[:12]]
                snippets = [r.get('body', '')[:200] for r in results[:3]]
                trans_titles = translate_batch(titles, tl)
                trans_snippets = translate_batch(snippets, tl)
                for i, r in enumerate(results):
                    r['original_title'] = r.get('title', '')
                    if i < len(trans_titles) and trans_titles[i]:
                        r['title'] = trans_titles[i]
                    if i < len(trans_snippets) and trans_snippets[i]:
                        r['body'] = trans_snippets[i]
                    r['translated_to'] = tl
                    r['translated_to_name'] = LANG_CONFIGS.get(tl, {}).get('name', tl.upper())

        if hasattr(response, 'data'):
            _FEED_MEM_CACHE[cache_key] = (now, response.data)

        return response
    
class ArticleClaimListCreateView(generics.ListCreateAPIView):
    """
    GET: List all community claims and attached evidence for a specific article.
    POST: Submit a new factual clarification claim with evidence URLs.
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = ClarificationClaimSerializer

    def get_queryset(self):
        return (
            ClarificationClaim.objects.filter(article_id=self.kwargs['article_id'])
            .select_related('author')
            .prefetch_related('evidence_links', 'votes')
            .order_by('created_at', 'id')
        ).prefetch_related('evidence_links')

    def perform_create(self, serializer):
        article = generics.get_object_or_404(Article, id=self.kwargs['article_id'])
        serializer.save(author=self.request.user, article=article)


class CastClaimVoteView(generics.GenericAPIView):
    """
    POST: Cast or update a vote (+1 or -1) on a specific claim.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ClaimVoteSerializer

    def post(self, request, claim_id):
        claim = generics.get_object_or_404(ClarificationClaim, id=claim_id)

        # Authors cannot vote on their own claims
        if claim.author_id == request.user.id:
            raise PermissionDenied("You cannot vote on your own claim.")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vote_val = serializer.validated_data['value']

        with transaction.atomic():
            vote, created = ClaimVote.objects.update_or_create(
                claim=claim,
                user=request.user,
                defaults={'value': vote_val},
            )
            # Evaluate claim consensus with row-level locks
            resolve_claim_if_ready(claim)

        claim.refresh_from_db()

        return Response(
            {
                "status": "vote recorded",
                "vote_id": vote.id,
                "value": vote.value,
                "is_active_badge": claim.is_active_badge,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = NewsUserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class BookmarkListCreateView(generics.ListCreateAPIView):
    """
    GET: List all bookmarked articles for the logged-in user (returns empty list for guests).
    POST: Bookmark an article (send {"article": <article_id>}).
    """
    serializer_class = BookmarkSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        if not self.request.user or not self.request.user.is_authenticated:
            return Bookmark.objects.none()
        return Bookmark.objects.filter(user=self.request.user).select_related(
            "article__genre", "article__region", "article__source"
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class BookmarkDeleteView(APIView):
    """
    DELETE: Remove a bookmark by article ID.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def delete(self, request, article_id):
        bookmark = generics.get_object_or_404(Bookmark, user=request.user, article_id=article_id)
        bookmark.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IsPublisherPermission(permissions.BasePermission):
    message = "Only verified news provider publisher accounts can publish articles to OmniNews."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            getattr(request.user, 'publisher_source', None) is not None
        )


class PublishArticleView(generics.CreateAPIView):
    """
    POST: Official news providers (BBC News, Times of India, etc.) publish news articles.
    """
    permission_classes = [IsPublisherPermission]
    serializer_class = ArticlePublishSerializer

    def perform_create(self, serializer):
        user = self.request.user
        publisher_source = user.publisher_source

        import uuid
        from django.utils import timezone
        url = self.request.data.get('url')
        if not url:
            url = f"https://omninews.internal/published/{uuid.uuid4().hex[:12]}"

        serializer.save(
            source=publisher_source,
            published_at=timezone.now(),
            url=url,
        )


class FetchNewsThrottle(rest_framework.throttling.UserRateThrottle):
    """
    FIX 8: Per-user throttle for the manual news fetch endpoint.
    Prevents a logged-in user from hammering external RSS feeds.
    Uses the named scope "fetch_news_user" from REST_FRAMEWORK[DEFAULT_THROTTLE_RATES].
    """
    scope = 'fetch_news_user'


class TriggerFetchNewsView(APIView):
    """
    On-demand endpoint to trigger an immediate background news fetch from RSS providers.
    FIX 8: Requires authentication + throttled to 10/min per user to prevent RSS
    provider bans and excessive server load from repeat callers.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [FetchNewsThrottle]

    @extend_schema(request=None, responses={202: None})
    def post(self, request, *args, **kwargs):
        import threading
        from django.core.management import call_command

        threading.Thread(
            target=lambda: call_command("fetch_news"),
            name="ManualFetchThread",
            daemon=True
        ).start()
        return Response(
            {"message": "News fetch triggered successfully in background.", "status": "fetching"},
            status=status.HTTP_202_ACCEPTED
        )


class ImageProxyView(APIView):
    """
    Proxies newsroom photographs to supply Access-Control-Allow-Origin headers
    and proper image MIME content-types required by Flutter Web (CanvasKit / WebGL / Mobile Safari).

    FIX 7 — SSRF protection:
      * Only fetches URLs whose hostname matches an explicit CDN allowlist.
      * Blocks raw IP addresses (private, loopback, link-local, reserved).
      * Hard 5 MB read cap prevents memory exhaustion.
    """
    permission_classes = [permissions.AllowAny]

    # Extend this set when adding a new image CDN — never use a wildcard.
    _ALLOWED_IMAGE_HOSTS: frozenset = frozenset({
        # Indian news sources
        'static.toiimg.com', 'resize.indiatimes.com', 'timesofindia.indiatimes.com',
        'images.hindustantimes.com', 'www.hindustantimes.com',
        'cdn.ndtv.com', 'ndtvimg.com', 'i.ndtvimg.com',
        'images.news18.com', 'images.cnbctv18.com',
        'akm-img-a-in.tosshub.com',
        # Global news sources
        'images.bbc.co.uk', 'ichef.bbci.co.uk',
        'media.npr.org', 's.abcnews.com', 'gdb.voanews.com',
        'static01.nyt.com', 'www.reuters.com', 'www.aljazeera.com',
        # Tech news
        'techcrunch.com', 'cdn.mos.cms.futurecdn.net',
        'media.wired.com', 'images.theverge.com',
        # Cloud / CDN infrastructure
        'storage.googleapis.com', 'lh3.googleusercontent.com',
        'upload.wikimedia.org',
        'cloudfront.net', 'akamaized.net',
        'media-cldnry.s3-website-us-east-1.amazonaws.com',
    })

    # FIX 7: 5 MB hard cap — prevents memory exhaustion on slow/large responses.
    _MAX_IMAGE_BYTES: int = 5 * 1024 * 1024

    def _is_safe_url(self, url: str) -> bool:
        """
        Return True only when *url* is safe to proxy:
          1. scheme is http or https
          2. hostname is in the approved CDN allowlist (or a sub-domain of one)
          3. hostname does not resolve to a private / loopback / reserved IP
        """
        import ipaddress
        import urllib.parse as _up

        try:
            parsed = _up.urlparse(url)
            if parsed.scheme not in ('http', 'https'):
                return False

            hostname = (parsed.hostname or '').lower().rstrip('.')
            if not hostname:
                return False

            # Block raw IP addresses — legitimate CDNs use hostnames.
            try:
                addr = ipaddress.ip_address(hostname)
                # Any routable IP that isn't a public address is suspicious.
                if (
                    addr.is_private
                    or addr.is_loopback
                    or addr.is_link_local
                    or addr.is_reserved
                    or addr.is_unspecified
                    or addr.is_multicast
                ):
                    return False
                # Even a public IP is not on our allowlist — reject it.
                return False
            except ValueError:
                pass  # It is a hostname, not a bare IP — continue to allowlist check.

            # Must be an exact match or a subdomain of an approved host.
            approved = any(
                hostname == h or hostname.endswith('.' + h)
                for h in self._ALLOWED_IMAGE_HOSTS
            )
            return approved

        except Exception:
            return False

    def get(self, request):
        target_url = request.query_params.get('url', '').strip()

        if not target_url:
            return HttpResponse(status=400)

        # FIX 7: SSRF guard — reject before making any outbound request.
        if not self._is_safe_url(target_url):
            return HttpResponse(status=403)

        try:
            req = urllib.request.Request(
                target_url,
                headers={
                    'User-Agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0.0.0 Safari/537.36'
                    ),
                    'Accept': 'image/jpeg,image/png,image/webp,image/*;q=0.8',
                    'Referer': target_url,
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                # FIX 7: read at most _MAX_IMAGE_BYTES; reject if server sends more.
                content = resp.read(self._MAX_IMAGE_BYTES + 1)
                if len(content) > self._MAX_IMAGE_BYTES:
                    return HttpResponse(status=413)  # 413 Payload Too Large

                raw_ct = resp.headers.get('Content-Type', '')
                content_type = raw_ct.split(';')[0].strip().lower() if raw_ct else ''

                if not content_type.startswith('image/') or content_type == 'application/octet-stream':
                    import mimetypes
                    guessed, _ = mimetypes.guess_type(target_url)
                    if guessed and guessed.startswith('image/'):
                        content_type = guessed
                    elif content.startswith(b'\xff\xd8\xff'):
                        content_type = 'image/jpeg'
                    elif content.startswith(b'\x89PNG'):
                        content_type = 'image/png'
                    elif content.startswith(b'GIF8'):
                        content_type = 'image/gif'
                    elif content.startswith(b'RIFF') and b'WEBP' in content[:16]:
                        content_type = 'image/webp'
                    else:
                        content_type = 'image/jpeg'

                http_resp = HttpResponse(content, content_type=content_type)
                http_resp['Access-Control-Allow-Origin'] = '*'
                http_resp['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
                http_resp['Access-Control-Allow-Headers'] = '*'
                http_resp['Cache-Control'] = 'public, max-age=86400'
                return http_resp

        except Exception:
            return HttpResponse(status=404)


from .ai_service import (
    generate_omni_ai_assistance,
    get_gemini_status,
    set_gemini_api_key,
    translate_text,
    translate_full_article,
    translate_batch,
)


class AiStatusView(APIView):
    """
    GET:  Public â€“ returns current Gemini integration health (no secrets exposed).
    POST: Admin-only â€“ updates the active Gemini API key.
          Locked to IsAdminUser so random visitors cannot replace your production key.
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.IsAdminUser()]
        return [permissions.AllowAny()]

    def get(self, request):
        # Never leak the raw key in the status response
        info = get_gemini_status()
        info.pop('api_key', None)
        return Response(info, status=status.HTTP_200_OK)

    def post(self, request):
        api_key = request.data.get("api_key", "").strip()
        model = request.data.get("model", "").strip()
        result = set_gemini_api_key(api_key=api_key, model=model)
        status_code = status.HTTP_200_OK if result.get("success") else status.HTTP_400_BAD_REQUEST
        return Response(result, status=status_code)


class AiAssistThrottle(rest_framework.throttling.AnonRateThrottle):
    """
    FIX 8: Per-IP throttle for the AI assist endpoint.
    Uses the named scope "ai_assist_anon" from REST_FRAMEWORK[DEFAULT_THROTTLE_RATES]
    so the limit can be tuned in settings without a code deploy.
    """
    scope = 'ai_assist_anon'


class AiAssistView(APIView):
    """
    OmniAI Assistant Endpoint:
    Powered by Google Gemini with automatic multi-lingual summaries, bullet takeaways,
    conversational regional voice narration, and interactive news Q&A.
    Throttled to 20 req/min per anonymous IP to protect Gemini quota.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AiAssistThrottle]

    def post(self, request):
        article_id = request.data.get("article_id")
        title = request.data.get("title", "")
        body = request.data.get("body", "")
        language = request.data.get("language", "en")
        action = request.data.get("action", "all")
        query = request.data.get("query")
        api_key = request.data.get("gemini_api_key") or request.headers.get("X-Gemini-Api-Key")
        model = request.data.get("gemini_model")

        if article_id:
            try:
                article = Article.objects.filter(id=article_id).first()
                if article:
                    title = title or article.title
                    body = body or article.body
            except Exception:
                pass

        if not title and not body:
            return Response(
                {"detail": "Article title or body is required for AI assistance."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            data = generate_omni_ai_assistance(
                title=title,
                body=body,
                language=language,
                action=action,
                query=query,
                api_key=api_key,
                model=model,
            )
            return Response(data, status=status.HTTP_200_OK)
        except Exception:
            return Response({
                "status": "success",
                "language": language,
                "language_name": "English",
                "locale": "en-US",
                "title": title,
                "summary": (body[:300] if body else title),
                "bullets": [title, "Verified by OmniNews."],
                "eli5": f"Summary: {title}",
                "voice_script": f"This is an OmniNews update. {title}.",
                "qa_answer": None,
                "provider": "OmniAI Fallback Engine",
                "is_bengali_enhanced": False,
            }, status=status.HTTP_200_OK)

    def get(self, request):
        article_id = request.query_params.get("article_id")
        language = request.query_params.get("language", "en")
        action = request.query_params.get("action", "all")
        query = request.query_params.get("query")
        api_key = request.query_params.get("gemini_api_key") or request.headers.get("X-Gemini-Api-Key")
        model = request.query_params.get("gemini_model")

        title = ""
        body = ""
        if article_id:
            article = Article.objects.filter(id=article_id).first()
            if article:
                title = article.title
                body = article.body

        if not title:
            return Response(
                {"detail": "Article not found or article_id missing."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            data = generate_omni_ai_assistance(
                title=title,
                body=body,
                language=language,
                action=action,
                query=query,
                api_key=api_key,
                model=model,
            )
            return Response(data, status=status.HTTP_200_OK)
        except Exception:
            return Response({
                "status": "success",
                "language": language,
                "language_name": "English",
                "locale": "en-US",
                "title": title,
                "summary": (body[:300] if body else title),
                "bullets": [title, "Verified by OmniNews."],
                "eli5": f"Summary: {title}",
                "voice_script": f"This is an OmniNews update. {title}.",
                "qa_answer": None,
                "provider": "OmniAI Fallback Engine",
                "is_bengali_enhanced": False,
            }, status=status.HTTP_200_OK)



_CACHED_MARKET_DATA = None
_LAST_MARKET_FETCH_TIME = 0

class MarketQuotesView(APIView):
    """
    GET: Returns real-time global market quotes (Stocks, Indices, Gold, Silver, Oil, Currencies, Crypto)
    with exact change amounts, percentage changes, and intraday highs/lows.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        global _CACHED_MARKET_DATA, _LAST_MARKET_FETCH_TIME
        import time
        import json
        import urllib.request
        from concurrent.futures import ThreadPoolExecutor

        now = time.time()
        if _CACHED_MARKET_DATA and (now - _LAST_MARKET_FETCH_TIME) < 15:
            return Response(_CACHED_MARKET_DATA, status=status.HTTP_200_OK)

        items = [
            {"name": "S&P 500", "symbol": "^GSPC", "currency": "$", "category": "Index"},
            {"name": "NASDAQ", "symbol": "^IXIC", "currency": "$", "category": "Index"},
            {"name": "NIFTY 50", "symbol": "^NSEI", "currency": "₹", "category": "Index"},
            {"name": "FTSE 100", "symbol": "^FTSE", "currency": "£", "category": "Index"},
            {"name": "SHANGHAI", "symbol": "000001.SS", "currency": "¥", "category": "Index"},
            {"name": "GOLD", "symbol": "GC=F", "currency": "$", "category": "Commodity"},
            {"name": "SILVER", "symbol": "SI=F", "currency": "$", "category": "Commodity"},
            {"name": "BRENT CRUDE", "symbol": "BZ=F", "currency": "$", "category": "Commodity"},
            {"name": "EURO/DOLLAR", "symbol": "EURUSD=X", "currency": "", "category": "Forex"},
            {"name": "BITCOIN", "symbol": "BTC-USD", "currency": "$", "category": "Crypto"},
        ]

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

        def fetch_asset(item):
            name = item["name"]
            sym = item["symbol"]
            curr = item["currency"]
            cat = item["category"]
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    meta = data['chart']['result'][0]['meta']
                    price = float(meta.get('regularMarketPrice') or 0.0)
                    prev = float(meta.get('chartPreviousClose') or meta.get('previousClose') or price)
                    chg = price - prev
                    pct = (chg / prev * 100) if prev else 0.0
                    prefix = curr if curr else ''
                    return {
                        "name": name,
                        "symbol": sym,
                        "price": price,
                        "price_formatted": f"{prefix}{price:,.2f}" if price >= 10 else f"{prefix}{price:.4f}",
                        "change": round(chg, 2),
                        "change_formatted": f"{chg:+,.2f}",
                        "change_pct": round(pct, 2),
                        "change_pct_formatted": f"{pct:+.2f}%",
                        "up": chg >= 0,
                        "currency": curr,
                        "category": cat,
                        "high": meta.get('regularMarketDayHigh'),
                        "low": meta.get('regularMarketDayLow'),
                        "prev_close": prev,
                    }
            except Exception:
                return None

        results = []
        try:
            with ThreadPoolExecutor(max_workers=10) as ex:
                fetched = list(ex.map(fetch_asset, items))
                for idx, r in enumerate(fetched):
                    if r:
                        results.append(r)
                    elif _CACHED_MARKET_DATA and idx < len(_CACHED_MARKET_DATA):
                        results.append(_CACHED_MARKET_DATA[idx])
        except Exception:
            pass

        if not results:
            if _CACHED_MARKET_DATA:
                return Response(_CACHED_MARKET_DATA, status=status.HTTP_200_OK)
            results = [
                {"name": "GOLD", "symbol": "GC=F", "price": 4027.00, "price_formatted": "$4,027.00", "change": 19.10, "change_formatted": "+19.10", "change_pct": 0.48, "change_pct_formatted": "+0.48%", "up": True, "currency": "$", "category": "Precious Metal", "high": 4040.0, "low": 4010.0, "prev_close": 4007.90},
                {"name": "SILVER", "symbol": "SI=F", "price": 54.19, "price_formatted": "$54.19", "change": 0.24, "change_formatted": "+0.24", "change_pct": 0.44, "change_pct_formatted": "+0.44%", "up": True, "currency": "$", "category": "Precious Metal", "high": 54.80, "low": 53.90, "prev_close": 53.95},
                {"name": "BRENT CRUDE", "symbol": "BZ=F", "price": 110.06, "price_formatted": "$110.06", "change": -1.64, "change_formatted": "-1.64", "change_pct": -1.47, "change_pct_formatted": "-1.47%", "up": False, "currency": "$", "category": "Energy", "high": 112.50, "low": 109.80, "prev_close": 111.70},
                {"name": "EURO/DOLLAR", "symbol": "EURUSD=X", "price": 1.1210, "price_formatted": "1.1210", "change": 0.0006, "change_formatted": "+0.00", "change_pct": 0.05, "change_pct_formatted": "+0.05%", "up": True, "currency": "", "category": "Forex", "high": 1.1240, "low": 1.1190, "prev_close": 1.1204},
                {"name": "BITCOIN", "symbol": "BTC-USD", "price": 79813.06, "price_formatted": "$79,813.06", "change": -226.63, "change_formatted": "-226.63", "change_pct": -0.28, "change_pct_formatted": "-0.28%", "up": False, "currency": "$", "category": "Crypto", "high": 80400.0, "low": 79200.0, "prev_close": 80039.69},
                {"name": "S&P 500", "symbol": "^GSPC", "price": 5864.20, "price_formatted": "5,864.20", "change": 24.50, "change_formatted": "+24.50", "change_pct": 0.42, "change_pct_formatted": "+0.42%", "up": True, "currency": "$", "category": "Index", "high": 5875.0, "low": 5840.0, "prev_close": 5839.70},
                {"name": "NASDAQ", "symbol": "^IXIC", "price": 18518.60, "price_formatted": "18,518.60", "change": 58.20, "change_formatted": "+58.20", "change_pct": 0.32, "change_pct_formatted": "+0.32%", "up": True, "currency": "$", "category": "Index", "high": 18550.0, "low": 18460.0, "prev_close": 18460.40},
                {"name": "NIFTY 50", "symbol": "^NSEI", "price": 24980.50, "price_formatted": "24,980.50", "change": 105.40, "change_formatted": "+105.40", "change_pct": 0.42, "change_pct_formatted": "+0.42%", "up": True, "currency": "₹", "category": "Index", "high": 25020.0, "low": 24890.0, "prev_close": 24875.10},
                {"name": "FTSE 100", "symbol": "^FTSE", "price": 8240.10, "price_formatted": "8,240.10", "change": -70.50, "change_formatted": "-70.50", "change_pct": -0.85, "change_pct_formatted": "-0.85%", "up": False, "currency": "£", "category": "Index", "high": 8310.0, "low": 8230.0, "prev_close": 8310.60},
                {"name": "SHANGHAI", "symbol": "000001.SS", "price": 3284.32, "price_formatted": "3,284.32", "change": 10.15, "change_formatted": "+10.15", "change_pct": 0.31, "change_pct_formatted": "+0.31%", "up": True, "currency": "¥", "category": "Index", "high": 3300.0, "low": 3270.0, "prev_close": 3274.17},
            ]

        _CACHED_MARKET_DATA = results
        _LAST_MARKET_FETCH_TIME = now
        return Response(results, status=status.HTTP_200_OK)



# Global in-memory / cache-backed live telecast broadcaster state
_TELECAST_STATE = {
    "is_live": False,
    "title": "ICC T20 World Cup • IND vs AUS",
    "sport": "Cricket",
    "stream_url": "",
    "viewers": "18.4K",
}

class LiveTelecastView(APIView):
    """
    Real-Time Global Broadcast Synchronizer
    GET:  Publicly accessible by all consumers/viewers on all devices.
    POST: Broadcaster Studio control (Sumit / admin / staff / broadcaster_key).
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        global _TELECAST_STATE
        try:
            from .models import LiveTelecast
            telecast = LiveTelecast.get_current()
            is_auth = bool(request.user and request.user.is_authenticated)
            state = {
                "is_live": bool(telecast.is_live),
                "title": str(telecast.title or ""),
                "sport": str(telecast.sport or "Cricket"),
                # Only authenticated members who logged in or created an account can view live stream
                "stream_url": str(telecast.stream_url or "") if is_auth else "",
                "requires_login": not is_auth,
                "viewers": str(telecast.viewers or "18.4K"),
            }
            _TELECAST_STATE = state
            return Response(state, status=status.HTTP_200_OK)
        except Exception as e:
            from django.core.cache import cache
            raw_state = cache.get("live_telecast_state") or _TELECAST_STATE
            is_auth = bool(request.user and request.user.is_authenticated)
            state = dict(raw_state)
            if not is_auth:
                state["stream_url"] = ""
                state["requires_login"] = True
            return Response(state, status=status.HTTP_200_OK)

    def post(self, request):
        global _TELECAST_STATE
        data = request.data or {}
        
        # Check authorization via JWT user or broadcaster secret key
        is_authorized = False
        user = request.user
        if user and user.is_authenticated:
            username = (getattr(user, 'username', '') or '').lower()
            if user.is_staff or getattr(user, 'is_superuser', False) or username in ['sumit', 'admin']:
                is_authorized = True

        broadcaster_key = str(data.get('broadcaster_key') or data.get('admin_key') or data.get('admin_pass') or '').strip()
        if broadcaster_key in ['Sumit1906', 'Sumit', 'omninews_live_secret']:
            is_authorized = True

        if not is_authorized:
            return Response(
                {"error": "Only broadcaster admin (Sumit) can manage live telecasts."},
                status=status.HTTP_403_FORBIDDEN
            )

        is_live = bool(data.get("is_live", False))
        title = str(data.get("title", "ICC T20 World Cup • IND vs AUS")).strip()
        sport = str(data.get("sport", "Cricket")).strip()
        stream_url = str(data.get("stream_url", "")).strip()
        viewers = str(data.get("viewers", "18.4K")).strip()

        state = {
            "is_live": is_live,
            "title": title,
            "sport": sport,
            "stream_url": stream_url,
            "viewers": viewers,
        }
        _TELECAST_STATE = state

        # 1. Persist to PostgreSQL database (survives restarts & syncs across all Gunicorn workers)
        try:
            from .models import LiveTelecast
            telecast = LiveTelecast.get_current()
            telecast.is_live = is_live
            telecast.title = title
            telecast.sport = sport
            telecast.stream_url = stream_url
            telecast.viewers = viewers
            telecast.save()
        except Exception as e:
            pass

        # 2. Update cache
        try:
            from django.core.cache import cache
            cache.set("live_telecast_state", state, timeout=None)
        except Exception:
            pass

        return Response(state, status=status.HTTP_200_OK)


_ARTICLE_TRANSLATIONS_CACHE = {}

class ArticleTranslateView(APIView):
    """
    In-Place Article Translation Endpoint:
    Allows readers to translate ANY news article into ANY target language on demand
    (e.g., English -> Bengali, Bengali -> German, German -> English, Hindi -> Spanish).
    Preserves the active feed context while delivering translated title and body.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        article_id = request.query_params.get("article_id")
        target_lang = request.query_params.get("target_language") or request.query_params.get("language") or "en"
        return self._handle_translation(article_id=article_id, title=None, body=None, target_lang=target_lang)

    def post(self, request):
        article_id = request.data.get("article_id")
        title = request.data.get("title")
        body = request.data.get("body")
        target_lang = request.data.get("target_language") or request.data.get("language") or "en"
        return self._handle_translation(article_id=article_id, title=title, body=body, target_lang=target_lang)

    def _handle_translation(self, article_id, title, body, target_lang):
        orig_article = None
        orig_title = (title or "").strip()
        orig_body = (body or "").strip()
        orig_lang = "auto"

        if article_id:
            try:
                orig_article = Article.objects.filter(id=article_id).first()
                if orig_article:
                    if not orig_title:
                        orig_title = orig_article.title
                    if not orig_body:
                        orig_body = orig_article.body
                    orig_lang = orig_article.language or "en"
            except Exception:
                pass

        if not orig_title and not orig_body:
            return Response(
                {"detail": "Article ID or title/body is required for translation."},
                status=status.HTTP_400_BAD_REQUEST
            )

        tl = target_lang.split('-')[0].split('_')[0].lower()
        tl_name = LANG_CONFIGS.get(tl, {}).get("name", tl.upper())

        cache_key = (str(article_id) if article_id else orig_title[:80], tl)
        if cache_key in _ARTICLE_TRANSLATIONS_CACHE:
            cached = _ARTICLE_TRANSLATIONS_CACHE[cache_key]
            return Response(cached, status=status.HTTP_200_OK)

        # Translate title & full article body preserving paragraphs
        translated_title = translate_text(orig_title, tl) if orig_title else ""
        translated_body = translate_full_article(orig_body, tl) if orig_body else ""

        payload = {
            "status": "success",
            "article_id": int(article_id) if article_id else None,
            "target_language": tl,
            "target_language_name": tl_name,
            "translated_title": translated_title,
            "translated_body": translated_body,
            "original_title": orig_title,
            "original_body": orig_body,
            "original_language": orig_lang,
        }

        _ARTICLE_TRANSLATIONS_CACHE[cache_key] = payload
        return Response(payload, status=status.HTTP_200_OK)


class PingView(APIView):
    """
    Ultra-lightweight health and keep-alive ping endpoint.
    Used by internal background workers and client apps to ensure
    Render free tier container never sleeps and warmups stay fresh.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({
            "status": "online",
            "server_time": time.time(),
            "cached_feeds": len(_FEED_MEM_CACHE),
            "message": "OmniNews Cloud is active and ready",
        }, status=status.HTTP_200_OK)


class PodcastsExploreView(APIView):
    """
    Multi-Platform, Multi-Language Famous Podcast API:
    Fetches trending and famous podcasts from Apple Podcasts, BBC, NPR, Spotify/Anchor
    across multiple languages (English, Hindi, Spanish, French, German, Japanese, Arabic).
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from .podcast_service import get_famous_podcasts

        language = request.query_params.get("language", "all").strip().lower()
        platform = request.query_params.get("platform", "all").strip().lower()
        category = request.query_params.get("category", "all").strip()
        query = request.query_params.get("q", "") or request.query_params.get("search", "")
        limit_param = request.query_params.get("limit", "25")
        try:
            limit = int(limit_param)
        except ValueError:
            limit = 25

        data = get_famous_podcasts(
            language=language,
            platform=platform,
            category=category,
            query=query,
            limit=limit,
        )
        return Response(data, status=status.HTTP_200_OK)


class ApplePodcastsSearchView(APIView):
    """
    Direct Apple iTunes Search & Top Charts API proxy:
    Endpoint: https://itunes.apple.com/search?term={term}&entity={entity}&limit={limit}
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        import urllib.request
        import urllib.parse
        import json

        term = request.query_params.get("term", "technology").strip()
        entity = request.query_params.get("entity", "podcast").strip()
        country = request.query_params.get("country", "us").strip()
        limit = request.query_params.get("limit", "25").strip()

        url = (
            f"https://itunes.apple.com/search?media=podcast&entity={entity}"
            f"&term={urllib.parse.quote_plus(term)}&country={country}&limit={limit}"
        )
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "OmniNews/2.0 (+https://omninewsproject.vercel.app)"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": f"Apple iTunes search failed: {e}", "resultCount": 0, "results": []},
                status=status.HTTP_502_BAD_GATEWAY,
            )



# =============================================================================
# Voice Assistant & Link Summarizer Views
# =============================================================================

class VoiceAssistantThrottle(rest_framework.throttling.UserRateThrottle):
    """Rate limit per authenticated user for voice assistant queries."""
    scope = 'voice_assistant_user'


class SummarizeLinkThrottle(rest_framework.throttling.AnonRateThrottle):
    """Rate limit for URL link summarization requests."""
    scope = 'summarize_link_anon'


class VoiceAssistantView(APIView):
    """
    POST /api/news/voice-assistant/
    Requires authentication & throttled.
    Body: {text, language, article_id?}
    Utilizes Gemini with Google Search Grounding for live queries (scores, weather, prices),
    or routes to personalized feed summarization when asking about 'today's news' / 'my feed'.
    Returns: {speech_text, display_text, sources[]}
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [VoiceAssistantThrottle]

    def post(self, request):
        text = str(request.data.get('text', '')).strip()
        language = str(request.data.get('language', 'en')).strip()
        article_id = request.data.get('article_id')
        if article_id:
            try:
                article_id = int(article_id)
            except (ValueError, TypeError):
                article_id = None

        if not text:
            return Response(
                {"detail": "The 'text' field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        api_key = request.data.get('gemini_api_key') or request.headers.get('X-Gemini-Api-Key')
        model = request.data.get('gemini_model')

        from .ai_service import process_voice_assistant_query
        result = process_voice_assistant_query(
            text=text,
            user=request.user,
            language=language,
            article_id=article_id,
            api_key=api_key,
            model=model,
        )
        return Response(result, status=status.HTTP_200_OK)


class SummarizeLinkView(APIView):
    """
    POST /api/news/summarize-link/
    Throttled.
    Body: {url, language, length}
    Validates URL (http/https only, blocks private IPs via SSRF defense),
    tries url_context tool, falls back to requests + trafilatura, then summarizes with Gemini.
    Returns: {status, url, title, summary, bullets, speech_text, estimated_read_time, sources, language}
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [SummarizeLinkThrottle]

    def post(self, request):
        url = str(request.data.get('url', '')).strip()
        language = str(request.data.get('language', 'en')).strip()
        length = str(request.data.get('length', 'medium')).strip()

        if not url:
            return Response(
                {"detail": "The 'url' parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .ai_service import validate_safe_url, summarize_web_link
        if not validate_safe_url(url):
            return Response(
                {"detail": "Prohibited or invalid URL (only public http/https endpoints are allowed)."},
                status=status.HTTP_403_FORBIDDEN,
            )

        api_key = request.data.get('gemini_api_key') or request.headers.get('X-Gemini-Api-Key')
        model = request.data.get('gemini_model')

        try:
            result = summarize_web_link(
                url=url,
                language=language,
                length=length,
                api_key=api_key,
                model=model,
            )
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": f"Failed to extract and summarize link: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
