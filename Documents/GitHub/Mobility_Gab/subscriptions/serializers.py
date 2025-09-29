"""Serializers for subscription domain."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from accounts.models import UserRoles
from accounts.serializers import UserSerializer
from core.models import NotificationLog, SOSAlert
from .models import Checkpoint, Payment, Rating, RideRequest, Subscription, SubscriptionPlan, Trip


User = get_user_model()


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ("id", "name", "description", "price_monthly", "trips_per_day", "is_active")


class SubscriptionSerializer(serializers.ModelSerializer):
    parent = UserSerializer(read_only=True)
    chauffeur = UserSerializer(read_only=True)
    plan = SubscriptionPlanSerializer(read_only=True)
    plan_id = serializers.PrimaryKeyRelatedField(queryset=SubscriptionPlan.objects.all(), source="plan", write_only=True)
    parent_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=UserRoles.PARENT),
        source="parent",
        write_only=True,
        required=False,
    )
    chauffeur_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=UserRoles.CHAUFFEUR),
        source="chauffeur",
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Subscription
        fields = (
            "id",
            "parent",
            "chauffeur",
            "plan",
            "plan_id",
            "price_monthly",
            "start_date",
            "next_due_date",
            "status",
            "last_payment_date",
            "notes",
            "active_child_name",
            "pickup_location",
            "dropoff_location",
        )

    def create(self, validated_data):
        user = self.context["request"].user
        validated_data.setdefault("parent", user)
        if not validated_data.get("next_due_date"):
            validated_data["next_due_date"] = timezone.now().date() + timedelta(days=30)
        return super().create(validated_data)


class PaymentSerializer(serializers.ModelSerializer):
    subscription = SubscriptionSerializer(read_only=True)
    subscription_id = serializers.PrimaryKeyRelatedField(queryset=Subscription.objects.all(), source="subscription", write_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "subscription",
            "subscription_id",
            "amount",
            "method",
            "status",
            "provider_reference",
            "provider_response",
            "created_at",
            "processed_at",
        )


class TripSerializer(serializers.ModelSerializer):
    subscription = SubscriptionSerializer(read_only=True)
    subscription_id = serializers.PrimaryKeyRelatedField(queryset=Subscription.objects.all(), source="subscription", write_only=True, required=False, allow_null=True)
    chauffeur = UserSerializer(read_only=True)
    parent = UserSerializer(read_only=True)

    class Meta:
        model = Trip
        fields = (
            "id",
            "subscription",
            "subscription_id",
            "chauffeur",
            "parent",
            "scheduled_date",
            "status",
            "started_at",
            "completed_at",
            "distance_km",
            "duration_minutes",
            "average_speed_kmh",
            "shared_tracking_url",
        )
        read_only_fields = ("chauffeur", "parent")


class CheckpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = Checkpoint
        fields = ("id", "trip", "checkpoint_type", "latitude", "longitude", "timestamp", "notes")
        read_only_fields = ("trip", "timestamp")


class RatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rating
        fields = ("id", "trip", "score", "comment", "created_at", "badge_suggestion")
        read_only_fields = ("created_at",)


class RideRequestSerializer(serializers.ModelSerializer):
    parent = UserSerializer(read_only=True)
    chauffeur = UserSerializer(read_only=True)
    trip = TripSerializer(read_only=True)

    class Meta:
        model = RideRequest
        fields = (
            "id",
            "parent",
            "chauffeur",
            "pickup_location",
            "dropoff_location",
            "notes",
            "requested_pickup_time",
            "status",
            "requested_at",
            "responded_at",
            "trip",
        )
        read_only_fields = ("status", "requested_at", "responded_at", "trip")

    def create(self, validated_data):
        parent = self.context["request"].user
        chauffeur_id = self.context["request"].data.get("chauffeur_id")
        try:
            chauffeur = User.objects.get(id=chauffeur_id, role=UserRoles.CHAUFFEUR)
        except User.DoesNotExist as exc:
            raise serializers.ValidationError({"chauffeur_id": "Chauffeur introuvable."}) from exc
        return RideRequest.objects.create(parent=parent, chauffeur=chauffeur, **validated_data)


class NotificationSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = NotificationLog
        fields = (
            "id",
            "user",
            "title",
            "message",
            "notification_type",
            "created_at",
            "read",
        )


class SOSAlertSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = SOSAlert
        fields = (
            "id",
            "user",
            "latitude",
            "longitude",
            "resolved",
            "resolved_at",
            "notes",
        )
        read_only_fields = ("resolved_at",)


class MobileMoneyWebhookSerializer(serializers.Serializer):
    provider_reference = serializers.CharField()
    amount = serializers.DecimalField(max_digits=9, decimal_places=2)
    status = serializers.ChoiceField(choices=("success", "failed"))
    subscription_id = serializers.PrimaryKeyRelatedField(queryset=Subscription.objects.all())

    def create(self, validated_data):
        subscription = validated_data["subscription_id"]
        payment = Payment.objects.create(
            subscription=subscription,
            amount=validated_data["amount"],
            method="mobile_money",
            status="success" if validated_data["status"] == "success" else "failed",
            provider_reference=validated_data["provider_reference"],
            provider_response=validated_data,
        )
        if payment.status == "success":
            subscription.last_payment_date = timezone.now().date()
            subscription.extend_next_due_date()
        return payment


class StripeWebhookSerializer(serializers.Serializer):
    event_id = serializers.CharField()
    amount = serializers.DecimalField(max_digits=9, decimal_places=2)
    currency = serializers.CharField()
    paid = serializers.BooleanField()
    subscription_id = serializers.PrimaryKeyRelatedField(queryset=Subscription.objects.all())

    def create(self, validated_data):
        subscription = validated_data["subscription_id"]
        status = "success" if validated_data["paid"] else "failed"
        payment = Payment.objects.create(
            subscription=subscription,
            amount=validated_data["amount"],
            method="stripe",
            status=status,
            provider_reference=validated_data["event_id"],
            provider_response=validated_data,
        )
        if status == "success":
            subscription.last_payment_date = timezone.now().date()
            subscription.extend_next_due_date()
        return payment

