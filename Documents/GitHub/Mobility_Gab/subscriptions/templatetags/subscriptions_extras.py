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
    except:
        return False

