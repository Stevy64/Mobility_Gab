from django import template
from subscriptions.models import MobilityPlusSubscription

register = template.Library()

@register.simple_tag
def user_has_mobility_plus(user):
    """Vérifier si un utilisateur a un abonnement Mobility Plus actif."""
    if not user or not user.is_authenticated:
        return False

    try:
        mobility_plus = user.mobility_plus_subscription
        return mobility_plus.is_active and mobility_plus.status == 'active'
    except Exception:
        return False

@register.filter
def trip_archived_for(trip, user):
    return trip.is_archived_for(user)

@register.filter
def request_archived_for(request, user):
    if user == request.parent:
        return request.parent_archived
    if user == request.chauffeur:
        return request.chauffeur_archived
    return False




