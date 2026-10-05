from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.db.models import Case, When, Value, IntegerField, F
from .models import Article, Genre, ClarificationClaim, ClaimVote
from .serializers import (
    ArticleSerializer,
    GenreSerializer,
    ClarificationClaimSerializer,
    ClaimVoteSerializer,
)


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

        # 1. Raw feed with '-id' tiebreaker
        if getattr(user, 'raw_feed', False):
            return Article.objects.all().order_by('-published_at', '-id')

        # Retrieve user preferences
        user_genres = user.genres.all()
        user_region = getattr(user, 'home_region', None)

        # Dynamic scoring: +2 for preferred genre, +1 for home region
        # 2. Ordered by '-total_score', '-published_at', and '-id' tiebreaker
        return Article.objects.annotate(
            genre_score=Case(
                When(genre__in=user_genres, then=Value(2)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            region_score=Case(
                When(region=user_region, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            total_score=F('genre_score') + F('region_score'),
        ).order_by('-total_score', '-published_at', '-id')


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
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        vote_val = serializer.validated_data['value']

        # update_or_create handles initial votes and toggling between +1 and -1 cleanly
        vote, created = ClaimVote.objects.update_or_create(
            claim=claim,
            user=request.user,
            defaults={'value': vote_val},
        )

        # Refresh claim to reflect updated badge status triggered by ClaimVote.save()
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