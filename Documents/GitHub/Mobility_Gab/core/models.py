from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base model with created/updated timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class NotificationLog(TimeStampedModel):
    """Stores notifications delivered to users."""

    NOTIFICATION_TYPES = [
        ("payment_success", "Paiement reçu"),
        ("payment_failed", "Paiement échoué"),
        ("subscription_overdue", "Abonnement en retard"),
        ("subscription_suspended", "Compte suspendu"),
        ("trip_update", "Mise à jour de trajet"),
        ("sos_alert", "Alerte SOS"),
        ("admin_message", "Message admin"),
        ("chat_message", "Message de chat"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(max_length=64, choices=NOTIFICATION_TYPES)
    sent_via_email = models.BooleanField(default=False)
    sent_via_push = models.BooleanField(default=False)
    sent_via_sms = models.BooleanField(default=False)
    read = models.BooleanField(default=False)
    auto_delete_at = models.DateTimeField(null=True, blank=True, help_text="Date d'auto-suppression")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.user}"  # pragma: no cover
    
    def save(self, *args, **kwargs):
        # Auto-suppression après 24h pour les notifications de chat
        if self.notification_type == "chat_message" and not self.auto_delete_at:
            from django.utils import timezone
            from datetime import timedelta
            self.auto_delete_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)


class SOSAlert(TimeStampedModel):
    """SOS alerts triggered by a user."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"SOS #{self.pk} - {self.user}"  # pragma: no cover


class Badge(TimeStampedModel):
    """Gamification badges awarded to drivers."""

    BADGE_TYPES = [
        ("punctuality", "Ponctualité"),
        ("top_rated", "Top-rated"),
        ("zero_claims", "0 réclamations"),
        ("custom", "Personnalisé"),
    ]

    name = models.CharField(max_length=128)
    badge_type = models.CharField(max_length=32, choices=BADGE_TYPES, default="custom")
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=128, blank=True, help_text="Nom d'icône Bootstrap (ex: bi-trophy)")
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name  # pragma: no cover
