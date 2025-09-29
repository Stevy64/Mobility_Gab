"""Context processors for project-wide settings."""

from django.conf import settings


def core_settings(request):
    """Expose core settings to templates."""

    return {
        "project_name": "Mobility Gab",
        "support_email": "support@mobilitygab.local",
        "push_notifications_enabled": settings.PUSH_NOTIFICATIONS_ENABLED,
        "sms_notifications_enabled": settings.SMS_NOTIFICATIONS_ENABLED,
    }


