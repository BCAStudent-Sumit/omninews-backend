from django.db import models
from django.conf import settings
from django.db.models import Q

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
    url = models.URLField(max_length=2048, unique=True) # prevents duplicate ingestion
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


class ClarificationClaim(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='claims')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='claims')
    text = models.TextField()
    is_active_badge = models.BooleanField(
        default=False, 
        help_text="Whether this claim has earned a community badge"
    )
    karma_awarded = models.BooleanField(
        default=False,
        help_text="Ensures reputation payouts occur exactly once upon claim resolution"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Claim #{self.id} on Article {self.article_id}"


class Evidence(models.Model):
    claim = models.ForeignKey(ClarificationClaim, on_delete=models.CASCADE, related_name='evidence_links')
    url = models.URLField(max_length=500)
    title = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.url


class ClaimVote(models.Model):
    claim = models.ForeignKey(ClarificationClaim, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='claim_votes')
    value = models.SmallIntegerField()  # +1 or -1
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:

        constraints = [
    models.UniqueConstraint(fields=['claim', 'user'], name='unique_user_claim_vote'),
    models.CheckConstraint(
        condition=Q(value__in=[1, -1]),
        name='claim_vote_value_is_plus_or_minus_one',
    ),
]
    def __str__(self):
        return f"Vote {self.value} by User {self.user_id} on Claim {self.claim_id}"

class Bookmark(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookmarks",
    )
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="bookmarked_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "article")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} bookmarked {self.article_id}"