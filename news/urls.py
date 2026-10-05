from django.urls import path
from .views import (
    ArticleListView,
    GenreListView,
    FeedView,
    ArticleClaimListCreateView,
    CastClaimVoteView,
)

urlpatterns = [
    path('articles/', ArticleListView.as_view(), name='article-list'),
    path('genres/', GenreListView.as_view(), name='genre-list'),
    path('feed/', FeedView.as_view(), name='news-feed'),
    path('articles/<int:article_id>/claims/', ArticleClaimListCreateView.as_view(), name='article-claims'),
    path('claims/<int:claim_id>/vote/', CastClaimVoteView.as_view(), name='claim-vote'),
]