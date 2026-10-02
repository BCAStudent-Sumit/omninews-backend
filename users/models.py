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