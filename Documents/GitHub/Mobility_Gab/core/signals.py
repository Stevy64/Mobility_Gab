"""Core signals for automation."""

from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import User, UserRoles

from .models import NotificationLog, SOSAlert


@receiver(post_save, sender=NotificationLog)
def send_notification_email(sender, instance, created, **kwargs):
    """Send email when notification log created with email flag."""

    if not created or not instance.sent_via_email:
        return
    send_mail(
        subject=instance.title,
        message=instance.message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[instance.user.email],
        fail_silently=True,
    )


@receiver(post_save, sender=SOSAlert)
def notify_admin_sos(sender, instance, created, **kwargs):
    """Notify admins when SOS is triggered."""

    if not created:
        return
    admin_emails = [u.email for u in User.objects.filter(role=UserRoles.ADMIN)]
    if not admin_emails:
        admin_emails = ["admin@mobilitygab.local"]
    send_mail(
        subject="Alerte SOS déclenchée",
        message=f"L'utilisateur {instance.user} a déclenché une alerte SOS.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=admin_emails,
        fail_silently=True,
    )

