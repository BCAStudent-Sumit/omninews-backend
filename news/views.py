from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.db import transaction
from rest_framework.exceptions import PermissionDenied
from django.db.models import Case, When, Value, IntegerField, F, Prefetch
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from .models import Article, Genre, ClarificationClaim, ClaimVote, Bookmark
from .serializers import (
    ArticleSerializer,
    GenreSerializer,
    ClarificationClaimSerializer,
    ClaimVoteSerializer,
    NewsUserProfileSerializer,
    BookmarkSerializer,
)
from .scoring import resolve_claim_if_ready


class GenreListView(generics.ListAPIView):
    queryset = Genre.objects.all()
    serializer_class = GenreSerializer


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

        return queryset


class FeedView(generics.ListAPIView):
    serializer_class = ArticleSerializer
    permission_classes = [permissions.IsAuthenticated]

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

        genre_id = self.request.query_params.get("genre")
        region_id = self.request.query_params.get("region")
        clarify_status = self.request.query_params.get("clarify_status")

        if genre_id:
            queryset = queryset.filter(genre_id=genre_id)
        if region_id:
            queryset = queryset.filter(region_id=region_id)
        if clarify_status:
            queryset = queryset.filter(clarify_status=clarify_status)

        if getattr(user, "raw_feed", False):
            return queryset.order_by("-published_at", "-id")

        user_genres = user.genres.all()
        user_region = getattr(user, "home_region", None)

        # Region-safe check: prevents boosting null-region articles for users without a home region
        if user_region is not None:
            region_score = Case(
                When(region=user_region, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        else:
            region_score = Value(0, output_field=IntegerField())

        return queryset.annotate(
            genre_score=Case(
                When(genre__in=user_genres, then=Value(2)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            region_score=region_score,
            total_score=F("genre_score") + F("region_score"),
        ).order_by("-total_score", "-published_at", "-id")
    
class ArticleClaimListCreateView(generics.ListCreateAPIView):
    """
    GET: List all community claims and attached evidence for a specific article.
    POST: Submit a new factual clarification claim with evidence URLs.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ClarificationClaimSerializer

    def get_queryset(self):
        return ClarificationClaim.objects.filter(
            article_id=self.kwargs['article_id']
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
    GET: List all bookmarked articles for the logged-in user.
    POST: Bookmark an article (send {"article": <article_id>}).
    """
    serializer_class = BookmarkSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Bookmark.objects.filter(user=self.request.user).select_related("article")

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