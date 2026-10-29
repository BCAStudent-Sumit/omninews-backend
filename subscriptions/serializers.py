from rest_framework import serializers
from .models import Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            'id',
            'slug',
            'name',
            'price_inr',
            'interval',
            'features',
            'store_product_id',
            'active',
        ]


class UserSubscriptionStatusSerializer(serializers.Serializer):
    has_subscription = serializers.BooleanField()
    plan = PlanSerializer(allow_null=True)
    status = serializers.CharField(allow_null=True)
    current_period_end = serializers.DateTimeField(allow_null=True)
    entitlements = serializers.DictField()
