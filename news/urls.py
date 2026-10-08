from django.urls import path
from .views import (
    GenreListView,
    ArticleListView,
    FeedView,
    ArticleClaimListCreateView,
    CastClaimVoteView,
    UserProfileView,
    BookmarkListCreateView,
    BookmarkDeleteView,
)
urlpatterns = [
    path("genres/", GenreListView.as_view(), name="genre-list"),
    path("articles/", ArticleListView.as_view(), name="article-list"),
    path("feed/", FeedView.as_view(), name="news-feed"),
    path("articles/<int:article_id>/claims/", ArticleClaimListCreateView.as_view(), name="article-claims"),
    path("claims/<int:claim_id>/vote/", CastClaimVoteView.as_view(), name="claim-vote"),
    path("profile/", UserProfileView.as_view(), name="user-profile"),
    path("bookmarks/", BookmarkListCreateView.as_view(), name="user-bookmarks"),
    path("bookmarks/<int:article_id>/", BookmarkDeleteView.as_view(), name="bookmark-delete"),
]