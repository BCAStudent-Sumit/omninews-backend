from django.db import models
from django.conf import settings
from django.utils import timezone


class Plan(models.Model):
    INTERVAL_CHOICES = [
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
    ]

    slug = models.SlugField(max_length=50, unique=True, help_text="Unique plan slug e.g. 'pro', 'exclusive'")
    name = models.CharField(max_length=100)
    price_inr = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price in INR. Editable via Django admin.")
    interval = models.CharField(max_length=20, choices=INTERVAL_CHOICES, default='monthly')
    features = models.JSONField(default=list, blank=True, help_text="List of feature bullet points for display")
    store_product_id = models.CharField(
        max_length=150,
        blank=True,
        default='',
        help_text="In-App purchase product ID in Google Play / App Store / RevenueCat"
    )
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Subscription Plan"
        verbose_name_plural = "Subscription Plans"
        ordering = ['price_inr']

    def __str__(self):
        return f"{self.name} (₹{self.price_inr}/{self.interval})"


class Subscription(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('grace', 'Grace Period'),
        ('cancelled', 'Cancelled (Active until period end)'),
        ('expired', 'Expired'),
    ]

    PROVIDER_CHOICES = [
        ('revenuecat', 'RevenueCat'),
        ('stripe', 'Stripe'),
        ('manual', 'Manual / Admin'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions'
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name='subscriptions'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active'
    )
    current_period_end = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(
        max_length=30,
        choices=PROVIDER_CHOICES,
        default='manual'
    )
    provider_subscription_id = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Subscription"
        verbose_name_plural = "User Subscriptions"
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user} - {self.plan.name} ({self.status})"

    @property
    def is_currently_active(self) -> bool:
        """
        True if the subscription allows access:
        'active' or 'grace' or 'cancelled' before current_period_end.
        """
        if self.status in ('active', 'grace'):
            return True
        if self.status == 'cancelled':
            if self.current_period_end is None:
                return True
            return self.current_period_end > timezone.now()
        return False

    @property
    def entitlements(self) -> dict:
        """
        Returns {live_2d: bool, live_vr: bool} based on plan and status.
        """
        if not self.is_currently_active:
            return {'live_2d': False, 'live_vr': False}

        slug = (self.plan.slug or '').lower()
        if slug == 'exclusive':
            return {'live_2d': True, 'live_vr': True}
        if slug == 'pro':
            return {'live_2d': True, 'live_vr': False}
        return {'live_2d': False, 'live_vr': False}


class PaymentEvent(models.Model):
    provider = models.CharField(max_length=50)
    event_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    processed = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Payment Webhook Event"
        verbose_name_plural = "Payment Webhook Events"
        ordering = ['-received_at']

    def __str__(self):
        return f"[{self.provider}] {self.event_type} - {self.event_id}"
