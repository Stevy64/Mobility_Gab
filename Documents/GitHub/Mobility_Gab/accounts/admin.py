"""Admin registrations for accounts app."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import ChauffeurBadge, ChauffeurProfile, ParentProfile, Profile, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Rôle et statut",
            {
                "fields": (
                    "role",
                    "is_email_verified",
                    "is_suspended",
                    "suspended_until",
                    "suspended_reason",
                )
            },
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "role"),
            },
        ),
    )
    list_display = ("email", "get_full_name", "role", "is_active", "is_staff", "is_suspended")
    list_filter = ("role", "is_active", "is_staff", "is_suspended")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "push_notifications_enabled", "sms_notifications_enabled")
    search_fields = ("user__email", "phone")


@admin.register(ParentProfile)
class ParentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "emergency_contact_name", "emergency_contact_phone")
    search_fields = ("user__email", "emergency_contact_name", "emergency_contact_phone")


@admin.register(ChauffeurProfile)
class ChauffeurProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "driving_license_number",
        "vehicle_plate",
        "zone",
        "reliability_score",
    )
    search_fields = ("user__email", "driving_license_number", "vehicle_plate", "zone")
    list_filter = ("zone",)


@admin.register(ChauffeurBadge)
class ChauffeurBadgeAdmin(admin.ModelAdmin):
    list_display = ("chauffeur", "badge", "awarded_at", "awarded_by")
    search_fields = ("chauffeur__user__email", "badge__name", "awarded_by__email")
