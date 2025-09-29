"""Subscription signals for automation."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import NotificationLog
from .models import Payment, Subscription, SubscriptionStatus


@receiver(post_save, sender=Subscription)
def notify_subscription_created(sender, instance, created, **kwargs):
    if not created:
        return
    NotificationLog.objects.create(
        user=instance.parent,
        title="Abonnement confirmé",
        message=f"Votre abonnement {instance.plan.name} est créé.",
        notification_type="admin_message",
        sent_via_email=True,
    )


@receiver(post_save, sender=Payment)
def process_payment_status(sender, instance, created, **kwargs):
    if not created:
        return
    subscription = instance.subscription
    if instance.status == "success":
        subscription.activate()
        NotificationLog.objects.create(
            user=subscription.parent,
            title="Paiement reçu",
            message="Votre paiement a été reçu. Merci !",
            notification_type="payment_success",
            sent_via_email=True,
        )
    elif instance.status == "failed":
        subscription.set_overdue()
        NotificationLog.objects.create(
            user=subscription.parent,
            title="Paiement échoué",
            message="Votre paiement n'a pas abouti. Merci de réessayer.",
            notification_type="payment_failed",
            sent_via_email=True,
        )



