from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    karma = models.IntegerField(default=0)
    is_fact_checker = models.BooleanField(default=False)
    home_region = models.ForeignKey(
        "news.Region", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="residents",
    )
    genres = models.ManyToManyField("news.Genre", blank=True, related_name="followers")
    raw_feed = models.BooleanField(default=False)  # the 'Raw' toggle from your doc
    preferred_languages = models.CharField(max_length=255, default="en,hi", blank=True)
    preferred_city = models.CharField(max_length=100, default="", blank=True)
    publisher_source = models.ForeignKey(
        "news.Source", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="publishers",
        help_text="The news provider company this account belongs to (e.g. BBC News, Times of India)."
    )

    @property
    def is_publisher(self) -> bool:
        return self.publisher_source is not None