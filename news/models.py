from django.db import models
from django.conf import settings
from news.scoring import should_clarify


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


class ClarificationClaim(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='claims')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submitted_claims')
    text = models.CharField(max_length=500, help_text="The factual statement or context being clarified")
    is_active_badge = models.BooleanField(default=False, help_text="Whether this claim has earned a community badge")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Claim #{self.id} on Article #{self.article_id}"

    def recalculate_badge_status(self) -> bool:
        """
        Pulls all votes and voter karma from the DB, runs should_clarify,
        and persists the badge state.
        """
        votes_data = list(self.votes.values_list('value', 'user__karma'))
        qualified = should_clarify(votes_data)

        if self.is_active_badge != qualified:
            self.is_active_badge = qualified
            self.save(update_fields=['is_active_badge'])

            # Sync article clarify_status if badge becomes active
            if qualified and self.article.clarify_status != Article.ClarifyStatus.CLARIFIED:
                self.article.clarify_status = Article.ClarifyStatus.CLARIFIED
                self.article.save(update_fields=['clarify_status'])

        return qualified


class Evidence(models.Model):
    claim = models.ForeignKey(ClarificationClaim, on_delete=models.CASCADE, related_name='evidence_links')
    url = models.URLField(max_length=500)
    title = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or self.url


class ClaimVote(models.Model):
    claim = models.ForeignKey(ClarificationClaim, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='claim_votes')
    value = models.SmallIntegerField(help_text="+1 for agree/clarify, -1 for disagree")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['claim', 'user'], name='unique_user_claim_vote')
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.claim.recalculate_badge_status()

    def __str__(self):
        return f"Vote({self.value}) by {self.user} on Claim #{self.claim_id}"