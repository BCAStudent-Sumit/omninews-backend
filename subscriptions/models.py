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


class VrPairing(models.Model):
    code = models.CharField(max_length=6, db_index=True, help_text="6-digit pairing code for VR headset")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vr_pairings'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    failed_attempts = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "VR Pairing Code"
        verbose_name_plural = "VR Pairing Codes"
        ordering = ['-created_at']

    def is_valid(self) -> bool:
        return (
            not self.used
            and self.failed_attempts < 5
            and self.expires_at > timezone.now()
        )

    def __str__(self):
        status_str = "USED" if self.used else ("EXPIRED" if self.expires_at <= timezone.now() else "ACTIVE")
        return f"VR Code: {self.code} ({self.user.username}) - {status_str}"


class VrSessionLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vr_sessions'
    )
    session_id = models.CharField(max_length=64, db_index=True)
    telecast_id = models.IntegerField(null=True, blank=True)
    action = models.CharField(max_length=20, default='start')
    watch_time_seconds = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "VR Session Log"
        verbose_name_plural = "VR Session Logs"
        ordering = ['-created_at']

    def __str__(self):
        return f"VR Session {self.session_id} - User {self.user_id} - {self.watch_time_seconds}s"
