"""Admin registrations for subscriptions."""

from django.contrib import admin

from .models import Checkpoint, Payment, Rating, Subscription, SubscriptionPlan, Trip


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price_monthly", "trips_per_day", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "description")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "parent",
        "chauffeur",
        "plan",
        "price_monthly",
        "status",
        "start_date",
        "next_due_date",
    )
    list_filter = ("status", "plan")
    search_fields = ("parent__email", "chauffeur__email")
    autocomplete_fields = ("parent", "chauffeur", "plan", "created_by")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "subscription",
        "amount",
        "method",
        "status",
        "created_at",
        "provider_reference",
    )
    list_filter = ("method", "status")
    search_fields = ("subscription__parent__email", "provider_reference")
    autocomplete_fields = ("subscription", "initiated_by")


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = (
        "subscription",
        "scheduled_date",
        "status",
        "started_at",
        "completed_at",
    )
    list_filter = ("status", "scheduled_date")
    search_fields = ("subscription__parent__email", "subscription__chauffeur__email")
    autocomplete_fields = ("subscription", "chauffeur", "parent")


@admin.register(Checkpoint)
class CheckpointAdmin(admin.ModelAdmin):
    list_display = ("trip", "checkpoint_type", "timestamp")
    list_filter = ("checkpoint_type",)
    search_fields = ("trip__subscription__parent__email",)
    autocomplete_fields = ("trip",)


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ("chauffeur", "score", "parent", "created_at")
    list_filter = ("score",)
    search_fields = ("chauffeur__email", "parent__email")
    autocomplete_fields = ("trip", "parent", "chauffeur")
