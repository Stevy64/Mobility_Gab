"""
Utilitaires pour l'application Core.

Ce fichier contient des fonctions utilitaires communes utilisées dans toute l'application,
notamment pour la géolocalisation, le calcul de distances et le matching des chauffeurs.
"""

import math
from typing import List, Optional, Tuple

from django.db.models import Q, QuerySet
from accounts.models import ChauffeurProfile, UserRoles


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcule la distance entre deux points GPS en utilisant la formule de Haversine.
    
    Args:
        lat1, lon1: Coordonnées du premier point (latitude, longitude)
        lat2, lon2: Coordonnées du second point (latitude, longitude)
        
    Returns:
        float: Distance en kilomètres entre les deux points
        
    Note:
        Cette fonction utilise la formule de Haversine qui donne une bonne approximation
        de la distance sur une sphère. Pour des calculs très précis sur de longues distances,
        il faudrait utiliser des formules plus complexes tenant compte de l'ellipsoïde terrestre.
    """
    # Rayon de la Terre en kilomètres
    R = 6371.0
    
    # Conversion des degrés en radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    # Différences
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    # Formule de Haversine
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    # Distance finale
    distance = R * c
    return distance


def find_available_chauffeurs(
    zone: Optional[str] = None,
    pickup_lat: Optional[float] = None,
    pickup_lon: Optional[float] = None,
    max_distance_km: float = 10.0,
    min_reliability_score: float = 3.0
) -> QuerySet[ChauffeurProfile]:
    """
    Trouve les chauffeurs disponibles selon différents critères.
    
    Args:
        zone: Zone géographique préférée (optionnel)
        pickup_lat, pickup_lon: Coordonnées GPS du point de départ (optionnel)
        max_distance_km: Distance maximale en km du chauffeur par rapport au pickup
        min_reliability_score: Score de fiabilité minimum requis
        
    Returns:
        QuerySet[ChauffeurProfile]: Chauffeurs disponibles triés par pertinence
        
    Note:
        Les chauffeurs sont triés par :
        1. Distance (si coordonnées fournies)
        2. Score de fiabilité (décroissant)
        3. Nombre total d'avis (décroissant)
    """
    # Requête de base : chauffeurs disponibles avec un bon score
    queryset = ChauffeurProfile.objects.filter(
        user__role=UserRoles.CHAUFFEUR,
        user__is_active=True,
        user__is_suspended=False,
        is_available=True,
        reliability_score__gte=min_reliability_score,
    ).select_related('user')
    
    # Filtrage par zone si spécifiée
    if zone:
        queryset = queryset.filter(
            Q(zone__icontains=zone) | Q(zone__iexact=zone)
        )
    
    # Si coordonnées GPS fournies, filtrer par distance
    if pickup_lat is not None and pickup_lon is not None:
        # Note: Pour une vraie application, il faudrait utiliser PostGIS ou une base spatiale
        # Ici on fait un filtrage basique puis on calcule les distances en Python
        chauffeurs_with_gps = queryset.filter(
            current_latitude__isnull=False,
            current_longitude__isnull=False
        )
        
        # Calcul des distances et filtrage
        valid_chauffeurs = []
        for chauffeur in chauffeurs_with_gps:
            distance = calculate_distance(
                pickup_lat, pickup_lon,
                float(chauffeur.current_latitude), 
                float(chauffeur.current_longitude)
            )
            if distance <= max_distance_km:
                # Ajouter la distance calculée comme attribut temporaire
                chauffeur.calculated_distance = distance
                valid_chauffeurs.append(chauffeur)
        
        # Trier par distance puis par score de fiabilité
        valid_chauffeurs.sort(key=lambda c: (c.calculated_distance, -c.reliability_score))
        
        # Retourner les IDs pour refaire une queryset Django
        if valid_chauffeurs:
            chauffeur_ids = [c.id for c in valid_chauffeurs]
            # Préserver l'ordre de tri
            queryset = ChauffeurProfile.objects.filter(id__in=chauffeur_ids)
            # Appliquer l'ordre manuellement
            preserved_order = {id: index for index, id in enumerate(chauffeur_ids)}
            queryset = sorted(queryset, key=lambda c: preserved_order[c.id])
            return queryset
        else:
            # Aucun chauffeur dans le rayon, retourner queryset vide
            return ChauffeurProfile.objects.none()
    
    # Tri par défaut : score de fiabilité puis nombre d'avis
    return queryset.order_by('-reliability_score', '-total_ratings')


def get_estimated_arrival_time(
    chauffeur_lat: float, 
    chauffeur_lon: float, 
    pickup_lat: float, 
    pickup_lon: float,
    average_speed_kmh: float = 30.0
) -> int:
    """
    Estime le temps d'arrivée d'un chauffeur au point de pickup.
    
    Args:
        chauffeur_lat, chauffeur_lon: Position actuelle du chauffeur
        pickup_lat, pickup_lon: Point de pickup
        average_speed_kmh: Vitesse moyenne estimée en ville
        
    Returns:
        int: Temps estimé en minutes
        
    Note:
        Cette estimation est basique et ne tient pas compte du trafic réel,
        des feux de circulation, ou de la topographie. Pour une application
        de production, il faudrait intégrer une API de routing comme Google Maps.
    """
    distance_km = calculate_distance(chauffeur_lat, chauffeur_lon, pickup_lat, pickup_lon)
    time_hours = distance_km / average_speed_kmh
    time_minutes = int(time_hours * 60)
    
    # Minimum 2 minutes (temps de préparation)
    return max(2, time_minutes)


def generate_zones_from_coordinates(lat: float, lon: float) -> List[str]:
    """
    Génère des suggestions de zones basées sur les coordonnées GPS.
    
    Args:
        lat, lon: Coordonnées GPS
        
    Returns:
        List[str]: Liste des zones suggérées
        
    Note:
        Cette fonction est un exemple basique. Dans une vraie application,
        il faudrait utiliser une API de géocodage inverse pour obtenir
        les vrais noms de quartiers/communes.
    """
    zones = []
    
    # Exemple basique basé sur des coordonnées de Yaoundé/Douala
    if 3.8 <= lat <= 4.1 and 11.4 <= lon <= 11.6:
        zones.extend(["Centre-ville", "Bastos", "Melen", "Ngousso"])
    elif 4.0 <= lat <= 4.1 and 9.6 <= lon <= 9.8:
        zones.extend(["Akwa", "Bonanjo", "Deido", "New Bell"])
    else:
        # Zone générique
        zones.append(f"Zone_{int(lat*10)}_{int(lon*10)}")
    
    return zones


def mock_gps_update(chauffeur_profile: ChauffeurProfile, 
                   target_lat: float, target_lon: float, 
                   step_size: float = 0.001) -> Tuple[float, float]:
    """
    Simule une mise à jour GPS progressive vers une destination.
    
    Args:
        chauffeur_profile: Profil du chauffeur à mettre à jour
        target_lat, target_lon: Coordonnées de destination
        step_size: Taille du pas de déplacement (en degrés)
        
    Returns:
        Tuple[float, float]: Nouvelles coordonnées (lat, lon)
        
    Note:
        Cette fonction est utilisée pour simuler le mouvement GPS
        en attendant l'intégration d'un vrai système de tracking.
    """
    current_lat = float(chauffeur_profile.current_latitude or 0)
    current_lon = float(chauffeur_profile.current_longitude or 0)
    
    # Calcul de la direction
    lat_diff = target_lat - current_lat
    lon_diff = target_lon - current_lon
    
    # Distance totale
    total_distance = math.sqrt(lat_diff**2 + lon_diff**2)
    
    if total_distance <= step_size:
        # Arrivé à destination
        new_lat, new_lon = target_lat, target_lon
    else:
        # Déplacement progressif
        ratio = step_size / total_distance
        new_lat = current_lat + (lat_diff * ratio)
        new_lon = current_lon + (lon_diff * ratio)
    
    # Mise à jour du profil
    chauffeur_profile.current_latitude = new_lat
    chauffeur_profile.current_longitude = new_lon
    chauffeur_profile.save(update_fields=['current_latitude', 'current_longitude'])
    
    return new_lat, new_lon