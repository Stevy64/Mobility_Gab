"""Celery tasks for subscription management."""

from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from accounts.models import UserRoles
from core.models import NotificationLog
from .models import Subscription, SubscriptionStatus


@shared_task
def handle_overdue_subscriptions(dry_run: bool = False):
    """Check subscriptions with passed due dates and update status.

    Args:
        dry_run: when True, compute the results without persisting changes.
    """

    today = timezone.now().date()
    grace_period = today - timedelta(days=5)

    overdue_subscriptions = Subscription.objects.filter(
        next_due_date__lt=today,
        status=SubscriptionStatus.ACTIVE,
    )
    overdue_ids = list(overdue_subscriptions.values_list("id", flat=True))

    if not dry_run:
        for sub in overdue_subscriptions:
            sub.set_overdue()
            NotificationLog.objects.create(
                user=sub.parent,
                title="Paiement en retard",
                message="Votre abonnement est en retard de paiement. Merci de régulariser sous 5 jours.",
                notification_type="subscription_overdue",
                sent_via_email=True,
            )

    suspended_subscriptions = Subscription.objects.filter(
        status=SubscriptionStatus.OVERDUE,
        next_due_date__lt=grace_period,
    )
    suspended_ids = list(suspended_subscriptions.values_list("id", flat=True))

    if not dry_run:
        for sub in suspended_subscriptions:
            sub.suspend("Retard de paiement > 5 jours")
            NotificationLog.objects.create(
                user=sub.parent,
                title="Compte suspendu",
                message="Votre abonnement est suspendu suite à un retard de paiement.",
                notification_type="subscription_suspended",
                sent_via_email=True,
            )

    return {
        "overdue": len(overdue_ids),
        "suspended": len(suspended_ids),
        "overdue_ids": overdue_ids,
        "suspended_ids": suspended_ids,
    }



