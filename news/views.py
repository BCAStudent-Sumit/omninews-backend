from rest_framework import generics, permissions
from django.db.models import Case, When, Value, IntegerField, F
from .models import Article, Genre
from .serializers import ArticleSerializer, GenreSerializer

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

        # If raw_feed is enabled, return newest first
        if getattr(user, 'raw_feed', False):
            return Article.objects.all().order_by('-published_at')

        # Retrieve user preferences
        user_genres = user.genres.all()
        user_region = getattr(user, 'home_region', None)

        # Dynamic scoring: +2 for preferred genre, +1 for home region
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
            total_score=F('genre_score') + F('region_score')
        ).order_by('-total_score', '-published_at')