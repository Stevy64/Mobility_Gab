"""Admin registrations for core models."""

from django.contrib import admin

from .models import Badge, NotificationLog, SOSAlert


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "notification_type", "created_at", "read")
    list_filter = ("notification_type", "sent_via_email", "sent_via_push", "read")
    search_fields = ("user__email", "title", "message")


@admin.register(SOSAlert)
class SOSAlertAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "resolved", "resolved_at")
    list_filter = ("resolved",)
    search_fields = ("user__email", "notes")


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ("name", "badge_type", "active", "icon")
    list_filter = ("badge_type", "active")
    search_fields = ("name", "description")
