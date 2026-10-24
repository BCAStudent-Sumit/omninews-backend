from rest_framework import serializers
from .models import User
from news.models import Genre, Region

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password')

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password']
        )
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    genres = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Genre.objects.all(),
        required=False
    )
    home_region = serializers.PrimaryKeyRelatedField(
        queryset=Region.objects.all(),
        required=False,
        allow_null=True
    )

    publisher_source_id = serializers.IntegerField(source="publisher_source.id", read_only=True)
    publisher_source_name = serializers.CharField(source="publisher_source.name", read_only=True)
    is_publisher = serializers.BooleanField(read_only=True)
    is_staff = serializers.BooleanField(read_only=True)
    is_superuser = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'genres', 'home_region', 'raw_feed',
            'preferred_languages', 'preferred_city',
            'is_publisher', 'publisher_source_id', 'publisher_source_name',
            'is_staff', 'is_superuser',
        )
        read_only_fields = ('id', 'username', 'email', 'is_publisher', 'publisher_source_id', 'publisher_source_name', 'is_staff', 'is_superuser')