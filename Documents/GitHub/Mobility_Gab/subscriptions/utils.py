"""
Utilitaires pour l'application Subscriptions.

Ce fichier contient des fonctions spécifiques à la gestion des abonnements
et des demandes de course. Les utilitaires géographiques avancés sont
maintenant dans core/utils.py
"""

from typing import Iterable, Optional

from django.contrib.auth import get_user_model
from django.db.models import Q

from accounts.models import UserRoles

User = get_user_model()


def find_available_chauffeurs(
    zone: Optional[str] = None,
    pickup_lat: Optional[float] = None,
    pickup_lon: Optional[float] = None,
    max_distance_km: float = 10.0
) -> Iterable[User]:
    """
    Trouve les chauffeurs disponibles avec support géolocalisation avancée.
    
    Args:
        zone: Zone géographique préférée
        pickup_lat, pickup_lon: Coordonnées GPS du point de départ
        max_distance_km: Distance maximale en km
        
    Returns:
        Iterable[User]: Chauffeurs disponibles triés par pertinence
        
    Note:
        Si les coordonnées GPS sont fournies, utilise le système avancé
        de core/utils.py, sinon utilise l'ancien système basé sur les zones.
    """
    # Si coordonnées GPS disponibles, utiliser le système avancé
    if pickup_lat is not None and pickup_lon is not None:
        from core.utils import find_available_chauffeurs as core_find_available
        chauffeur_profiles = core_find_available(
            zone=zone,
            pickup_lat=pickup_lat,
            pickup_lon=pickup_lon,
            max_distance_km=max_distance_km
        )
        # Retourner les utilisateurs correspondants
        return [profile.user for profile in chauffeur_profiles]
    
    # Système classique basé sur les zones
    chauffeurs = (
        User.objects.filter(
            role=UserRoles.CHAUFFEUR, 
            is_active=True, 
            is_suspended=False, 
            chauffeur_profile__is_available=True
        )
        .select_related("chauffeur_profile")
        .order_by("-chauffeur_profile__reliability_score", "username")
    )
    
    if zone:
        chauffeurs = chauffeurs.filter(
            Q(chauffeur_profile__zone__icontains=zone)
            | Q(chauffeur_profile__vehicle_plate__icontains=zone)
        )
    
    return chauffeurs
