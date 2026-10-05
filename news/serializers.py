from rest_framework import serializers
from .models import Article, Genre, Region, Source, ClarificationClaim, Evidence, ClaimVote


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

    class Meta:
        model = ClarificationClaim
        fields = [
            "id",
            "article",
            "author",
            "author_username",
            "text",
            "is_active_badge",
            "evidence_links",
            "evidence_urls",
            "created_at",
        ]
        read_only_fields = ["id", "article", "author", "is_active_badge", "created_at"]

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

    def get_active_claims(self, obj):
        # Exposes community-verified badges directly on the article payload
        active = obj.claims.filter(is_active_badge=True)
        return ClarificationClaimSerializer(active, many=True).data