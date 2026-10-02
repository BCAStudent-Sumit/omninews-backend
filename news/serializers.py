from rest_framework import serializers
from .models import Article, Genre, Region, Source

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

class ArticleSerializer(serializers.ModelSerializer):
    genre = GenreSerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    source = SourceSerializer(read_only=True)

    class Meta:
        model = Article
        fields = '__all__'