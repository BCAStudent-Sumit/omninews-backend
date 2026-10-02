from django.db import models


class Genre(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class Region(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)  # e.g. IN, DE

    def __str__(self):
        return self.name


class Source(models.Model):
    name = models.CharField(max_length=150)
    url = models.URLField(unique=True)
    credibility_score = models.FloatField(default=0.5)  # filled by Phase 3 AI later

    def __str__(self):
        return self.name


class Article(models.Model):
    class ClarifyStatus(models.TextChoices):
        NONE = "none", "Not flagged"
        FLAGGED = "flagged", "In Clarify queue"
        CLARIFIED = "clarified", "Clarified"

    title = models.CharField(max_length=300)
    body = models.TextField()
    url = models.URLField(unique=True)  # prevents duplicate ingestion
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="articles")
    genre = models.ForeignKey(Genre, on_delete=models.SET_NULL, null=True, related_name="articles")
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, related_name="articles")
    language = models.CharField(max_length=5, default="en")
    published_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    clarify_status = models.CharField(
        max_length=10, choices=ClarifyStatus.choices, default=ClarifyStatus.NONE
    )

    class Meta:
        ordering = ["-published_at"]
        indexes = [models.Index(fields=["-published_at"])]

    def __str__(self):
        return self.title