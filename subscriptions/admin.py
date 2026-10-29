from django.contrib import admin
from .models import Plan, Subscription, PaymentEvent, VrPairing


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'price_inr', 'interval', 'store_product_id', 'active')
    list_editable = ('price_inr', 'active', 'store_product_id')
    search_fields = ('name', 'slug', 'store_product_id')
    list_filter = ('interval', 'active')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'status', 'current_period_end', 'provider', 'updated_at')
    list_filter = ('status', 'provider', 'plan')
    search_fields = ('user__username', 'user__email', 'provider_subscription_id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'provider', 'event_type', 'processed', 'received_at')
    list_filter = ('provider', 'processed', 'event_type')
    search_fields = ('event_id', 'event_type')
    readonly_fields = ('received_at',)


@admin.register(VrPairing)
class VrPairingAdmin(admin.ModelAdmin):
    list_display = ('code', 'user', 'used', 'failed_attempts', 'expires_at', 'created_at')
    list_filter = ('used',)
    search_fields = ('code', 'user__username', 'user__email')
    readonly_fields = ('created_at', 'expires_at')
