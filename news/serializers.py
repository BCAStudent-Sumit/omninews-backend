from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import Article, Genre, Region, Source, ClarificationClaim, Evidence, ClaimVote, Bookmark
from drf_spectacular.utils import extend_schema_field

User = get_user_model()

class GenreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = '__all__'


class RegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Region
        fields = '__all__'


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = '__all__'


class EvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Evidence
        fields = ["id", "url", "title", "created_at"]
        read_only_fields = ["id", "created_at"]


class ClarificationClaimSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source="author.username", read_only=True)
    evidence_links = EvidenceSerializer(many=True, read_only=True)
    evidence_urls = serializers.ListField(
        child=serializers.URLField(), write_only=True, required=False
    )
    agree_count = serializers.SerializerMethodField()
    disagree_count = serializers.SerializerMethodField()

    class Meta:
        model = ClarificationClaim
        fields = [
            "id",
            "article",
            "author",
            "author_username",
            "text",
            "is_active_badge",
            "agree_count",
            "disagree_count",
            "evidence_links",
            "evidence_urls",
            "created_at",
        ]
        read_only_fields = ["id", "article", "author", "is_active_badge", "created_at"]

    def get_agree_count(self, obj) -> int:
        return sum(1 for vote in obj.votes.all() if vote.value == 1)

    def get_disagree_count(self, obj) -> int:
        return sum(1 for vote in obj.votes.all() if vote.value == -1)

    def create(self, validated_data):
        evidence_urls = validated_data.pop("evidence_urls", [])
        claim = ClarificationClaim.objects.create(**validated_data)

        # Batch-create attached evidence links
        evidence_objects = [Evidence(claim=claim, url=url) for url in evidence_urls]
        if evidence_objects:
            Evidence.objects.bulk_create(evidence_objects)

        return claim

class ClaimVoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClaimVote
        fields = ["id", "claim", "value", "created_at"]
        read_only_fields = ["id", "claim", "created_at"]

    def validate_value(self, value):
        if value not in (1, -1):
            raise serializers.ValidationError("Vote value must be either 1 (agree) or -1 (disagree).")
        return value


class ArticleSerializer(serializers.ModelSerializer):
    genre = GenreSerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    source = SourceSerializer(read_only=True)
    active_claims = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = '__all__'

    @extend_schema_field(ClarificationClaimSerializer(many=True))
    def get_active_claims(self, obj):
        if hasattr(obj, "prefetched_active_claims"):
            active = obj.prefetched_active_claims
        else:
            active = obj.claims.filter(is_active_badge=True).select_related("author")
        return ClarificationClaimSerializer(active, many=True).data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        img = data.get("image_url")
        if img:
            img_str = str(img).strip()
            # If the image host does not supply open CORS headers, route via local image proxy
            # BBC and Wikimedia already send Access-Control-Allow-Origin: *
            if not any(open_host in img_str for open_host in ["bbci.co.uk", "wikimedia.org"]):
                import urllib.parse
                if "/api/news/image-proxy/?url=" in img_str:
                    img_str = urllib.parse.unquote(img_str.split("/api/news/image-proxy/?url=")[-1])
                request = self.context.get("request")
                path = f"/api/news/image-proxy/?url={urllib.parse.quote(img_str)}"
                if request:
                    data["image_url"] = request.build_absolute_uri(path)
                else:
                    data["image_url"] = path
        return data


class ArticlePublishSerializer(serializers.ModelSerializer):
    genre_id = serializers.PrimaryKeyRelatedField(
        queryset=Genre.objects.all(), source="genre", required=False, allow_null=True
    )
    region_id = serializers.PrimaryKeyRelatedField(
        queryset=Region.objects.all(), source="region", required=False, allow_null=True
    )
    url = serializers.URLField(required=False, allow_blank=True)
    image_url = serializers.URLField(required=False, allow_blank=True)

    class Meta:
        model = Article
        fields = ["id", "title", "body", "genre_id", "region_id", "image_url", "url", "published_at"]
        read_only_fields = ["id", "published_at"]


class NewsUserProfileSerializer(serializers.ModelSerializer):
    home_region_name = serializers.CharField(source="home_region.name", read_only=True)
    preferred_genres = serializers.SlugRelatedField(
        source="genres", many=True, read_only=True, slug_field="name"
    )
    claims_submitted_count = serializers.SerializerMethodField()
    claims_verified_count = serializers.SerializerMethodField()
    votes_cast_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "karma",
            "home_region",
            "home_region_name",
            "preferred_genres",
            "preferred_languages",
            "preferred_city",
            "claims_submitted_count",
            "claims_verified_count",
            "votes_cast_count",
        ]
        read_only_fields = ["id", "username", "email", "karma"]

    def get_claims_submitted_count(self, obj) -> int:
        return obj.claims.count() if hasattr(obj, "claims") else 0

    def get_claims_verified_count(self, obj) -> int:
        return obj.claims.filter(is_active_badge=True).count() if hasattr(obj, "claims") else 0

    def get_votes_cast_count(self, obj) -> int:
        return obj.claim_votes.count() if hasattr(obj, "claim_votes") else 0


class BookmarkSerializer(serializers.ModelSerializer):
    article_title = serializers.CharField(source="article.title", read_only=True)
    article_url = serializers.CharField(source="article.url", read_only=True)
    article_details = ArticleSerializer(source="article", read_only=True)

    class Meta:
        model = Bookmark
        fields = ["id", "article", "article_title", "article_url", "article_details", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_article(self, value):
        user = self.context["request"].user
        if Bookmark.objects.filter(user=user, article=value).exists():
            raise serializers.ValidationError("Already bookmarked.")
        return value