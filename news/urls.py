from django.urls import path
from .views import ArticleListView, GenreListView

urlpatterns = [
    path('articles/', ArticleListView.as_view(), name='article-list'),
    path('genres/', GenreListView.as_view(), name='genre-list'),
]