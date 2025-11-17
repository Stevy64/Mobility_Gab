"""
Vues avancées pour les demandes de course avec géolocalisation et notifications temps réel.

Ce fichier contient le workflow complet de demande de course :
1. Particulier crée demande avec critères GPS
2. Système trouve chauffeurs éligibles par proximité
3. Notifications envoyées en temps réel aux chauffeurs
4. Acceptation déclenche tracking automatique
"""

import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.views import View
from django.views.generic import TemplateView, DetailView
from django.utils import timezone

from accounts.models import User, UserRoles
from core.models import NotificationLog
from core.utils import get_estimated_arrival_time, calculate_distance
from core.notifications import notification_service
from .forms import RideRequestForm
from .models import RideRequest, RideRequestStatus, Trip, Checkpoint
from .utils import find_available_chauffeurs
from datetime import timedelta


class AdvancedRideRequestCreateView(LoginRequiredMixin, View):
    """
    Vue avancée pour créer une demande de course avec critères GPS.
    
    Workflow complet :
    1. Particulier remplit formulaire avec géolocalisation
    2. Système trouve chauffeurs éligibles dans rayon défini
    3. Notifications push/SMS envoyées aux chauffeurs proches
    4. Premier à accepter déclenche création Trip + tracking
    """
    template_name = "subscriptions/ride_request_create_final.html"

    def dispatch(self, request, *args, **kwargs):
        """Vérifier que seuls les particuliers peuvent accéder."""
        if request.user.role != UserRoles.PARENT:
            messages.error(request, "Seuls les particuliers peuvent créer une demande de course.")
            return redirect("core:dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        """Afficher le formulaire avancé avec chauffeurs recommandés triés."""
        # Récupérer tous les chauffeurs disponibles avec infos Mobility+
        from .models import MobilityPlusSubscription
        from decimal import Decimal
        
        chauffeurs = User.objects.filter(
            role=UserRoles.CHAUFFEUR,
            is_active=True,
            chauffeur_profile__is_available=True
        ).select_related('chauffeur_profile').prefetch_related('mobility_plus_subscription')
        
        # Préparer la liste avec infos Mobility+ et distance (si position dispo)
        chauffeurs_list = []
        for chauffeur in chauffeurs:
            profile = chauffeur.chauffeur_profile
            
            # Vérifier Mobility+
            has_mobility_plus = False
            try:
                mobility_plus = chauffeur.mobility_plus_subscription
                has_mobility_plus = mobility_plus.is_active and mobility_plus.status == 'active'
            except:
                has_mobility_plus = False
            
            chauffeurs_list.append({
                'user': chauffeur,
                'has_mobility_plus': has_mobility_plus,
                'latitude': float(profile.current_latitude) if profile.current_latitude else None,
                'longitude': float(profile.current_longitude) if profile.current_longitude else None,
                'reliability_score': float(profile.reliability_score) if profile.reliability_score else 5.0,
            })
        
        # Trier : Mobility+ d'abord, puis par note (plus haute en premier)
        chauffeurs_list.sort(key=lambda x: (-x['has_mobility_plus'], -x['reliability_score']))
        
        # Extraire juste les objets User pour le form
        sorted_chauffeurs = [c['user'] for c in chauffeurs_list]
        top_recommended = sorted_chauffeurs[:10]  # Top 10 recommandés
        
        # Instancier le form avec les chauffeurs recommandés
        form = RideRequestForm(recommended_chauffeurs=top_recommended)
        
        return render(request, self.template_name, {
            "form": form,
        })

    def post(self, request):
        """Traiter la demande et notifier les chauffeurs éligibles."""
        form = RideRequestForm(request.POST)
        
        if form.is_valid():
            # Récupérer les données du formulaire
            pickup_lat = form.cleaned_data.get('pickup_latitude')
            pickup_lon = form.cleaned_data.get('pickup_longitude') 
            max_distance = form.cleaned_data.get('max_distance_km', 10)
            min_rating = form.cleaned_data.get('min_rating', 3.0)
            priority = form.cleaned_data.get('priority', 'closest')
            suggested_chauffeur = form.cleaned_data.get('suggested_chauffeur')
            
            # Trouver les chauffeurs éligibles avec géolocalisation
            eligible_chauffeurs = self._find_eligible_chauffeurs(
                pickup_lat=pickup_lat,
                pickup_lon=pickup_lon,
                max_distance_km=max_distance,
                min_rating=min_rating,
                priority=priority,
                suggested_chauffeur=suggested_chauffeur,
                need_child_seat=form.cleaned_data.get('need_child_seat', False)
            )
            
            if not eligible_chauffeurs:
                messages.error(request, 
                    f"Aucun chauffeur disponible dans un rayon de {max_distance}km "
                    f"avec une note d'au moins {min_rating}/5.")
                return render(request, self.template_name, {"form": form})
            
            # Créer la demande de course
            ride_request = RideRequest.objects.create(
                parent=request.user,
                chauffeur=None,  # Sera assigné lors de l'acceptation
                pickup_location=form.cleaned_data["pickup_location"],
                dropoff_location=form.cleaned_data["dropoff_location"],
                pickup_latitude=pickup_lat,
                pickup_longitude=pickup_lon,
                dropoff_latitude=form.cleaned_data.get('dropoff_latitude'),
                dropoff_longitude=form.cleaned_data.get('dropoff_longitude'),
                requested_pickup_time=form.cleaned_data["requested_pickup_time"],
                notes=form.cleaned_data.get("notes", ""),
                status='pending'
            )
            
            # Envoyer les notifications aux chauffeurs éligibles
            self._notify_eligible_chauffeurs(ride_request, eligible_chauffeurs)
            
            messages.success(request, 
                f"🚗 Demande envoyée à {len(eligible_chauffeurs)} chauffeur(s) éligible(s) ! "
                "Vous recevrez une notification dès qu'un chauffeur accepte.")
            
            return redirect("subscriptions:ride_request_waiting", pk=ride_request.pk)

        return render(request, self.template_name, {"form": form})
    
    def _find_eligible_chauffeurs(self, pickup_lat=None, pickup_lon=None, 
                                 max_distance_km=10, min_rating=3.0, priority='closest',
                                 suggested_chauffeur=None, need_child_seat=False):
        """
        Trouve les chauffeurs éligibles selon les critères spécifiés.
        
        Args:
            pickup_lat, pickup_lon: Coordonnées GPS du point de départ
            max_distance_km: Distance maximale acceptable
            min_rating: Note minimale requise
            priority: Critère de tri (closest, fastest, best_rated, cheapest)
            suggested_chauffeur: Chauffeur préféré si spécifié
            need_child_seat: Si siège enfant requis
            
        Returns:
            List[User]: Liste des chauffeurs éligibles triés par priorité
        """
        from core.utils import find_available_chauffeurs
        
        # Si chauffeur suggéré et disponible, le prioriser
        if suggested_chauffeur and suggested_chauffeur.chauffeur_profile.is_available:
            eligible = [suggested_chauffeur]
            
            # Ajouter d'autres chauffeurs comme backup
            if pickup_lat and pickup_lon:
                other_chauffeurs = find_available_chauffeurs(
                    pickup_lat=pickup_lat,
                    pickup_lon=pickup_lon,
                    max_distance_km=max_distance_km,
                    min_reliability_score=min_rating
                )
                
                for chauffeur_profile in other_chauffeurs[:4]:  # Max 4 autres
                    if chauffeur_profile.user != suggested_chauffeur:
                        eligible.append(chauffeur_profile.user)
                        
            return eligible
        
        # Recherche standard avec géolocalisation
        if pickup_lat and pickup_lon:
            chauffeur_profiles = find_available_chauffeurs(
                pickup_lat=pickup_lat,
                pickup_lon=pickup_lon,
                max_distance_km=max_distance_km,
                min_reliability_score=min_rating
            )
            
            eligible_chauffeurs = []
            for profile in chauffeur_profiles:
                # Filtrer par siège enfant si nécessaire
                if need_child_seat:
                    # En production, ajouter un champ child_seat_available au profil
                    # Pour l'instant, on suppose que tous les chauffeurs peuvent fournir
                    pass
                
                eligible_chauffeurs.append(profile.user)
                
                # Limiter à 5 chauffeurs maximum pour éviter le spam
                if len(eligible_chauffeurs) >= 5:
                    break
            
            return eligible_chauffeurs
        
        # Fallback sans géolocalisation (moins précis)
        return list(User.objects.filter(
            role=UserRoles.CHAUFFEUR,
            is_active=True,
            chauffeur_profile__is_available=True,
            chauffeur_profile__reliability_score__gte=min_rating
        ).select_related('chauffeur_profile')[:5])
    
    def _notify_eligible_chauffeurs(self, ride_request, eligible_chauffeurs):
        """
        Envoie les notifications aux chauffeurs éligibles.
        
        Utilise le système de notifications avancé pour envoyer
        des notifications push/SMS/email selon les préférences.
        """
        parent_name = ride_request.parent.get_full_name() or ride_request.parent.username
        pickup_time = ride_request.requested_pickup_time.strftime('%H:%M le %d/%m')
        
        for chauffeur in eligible_chauffeurs:
            # Calculer la distance si coordonnées disponibles
            distance_info = ""
            eta_info = ""
            
            if (ride_request.pickup_latitude and ride_request.pickup_longitude and
                chauffeur.chauffeur_profile.current_latitude and 
                chauffeur.chauffeur_profile.current_longitude):
                
                distance = calculate_distance(
                    float(chauffeur.chauffeur_profile.current_latitude),
                    float(chauffeur.chauffeur_profile.current_longitude),
                    float(ride_request.pickup_latitude),
                    float(ride_request.pickup_longitude)
                )
                distance_info = f" ({distance:.1f}km de vous)"
                
                # Calculer ETA
                eta = get_estimated_arrival_time(
                    float(chauffeur.chauffeur_profile.current_latitude),
                    float(chauffeur.chauffeur_profile.current_longitude),
                    float(ride_request.pickup_latitude),
                    float(ride_request.pickup_longitude)
                )
                eta_info = f" • ETA: {eta} min"
            
            # Titre et message personnalisés
            title = "🚗 Nouvelle demande de course"
            message = (
                f"{parent_name} demande une course{distance_info}\n"
                f"📍 De: {ride_request.pickup_location}\n"
                f"🏁 Vers: {ride_request.dropoff_location}\n"
                f"🕒 Heure: {pickup_time}{eta_info}"
            )
            
            # Envoyer via tous les canaux disponibles
            notification_service.send_notification(
                user=chauffeur,
                title=title,
                message=message,
                notification_type="trip_request",
                channels=['in_app', 'push', 'sms']  # Notification prioritaire
            )


@login_required
def accept_ride_request_advanced(request, pk):
    """
    Acceptation avancée d'une demande avec déclenchement automatique du tracking.
    
    Workflow :
    1. Chauffeur accepte la demande
    2. Création automatique du Trip
    3. Lancement du tracking GPS
    4. Notification au particulier
    5. Annulation des autres demandes en attente
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    if request.user.role != UserRoles.CHAUFFEUR:
        return JsonResponse({'error': 'Seuls les chauffeurs peuvent accepter'}, status=403)
    
    try:
        ride_request = get_object_or_404(RideRequest, pk=pk, status='pending')
        
        # Vérifier que le chauffeur était dans la liste des éligibles
        # (En production, stocker la liste des chauffeurs notifiés)
        
        # Accepter la demande
        ride_request.chauffeur = request.user
        ride_request.status = 'accepted'
        ride_request.accepted_at = timezone.now()
        ride_request.save()
        
        # Créer automatiquement le Trip pour le tracking
        trip = Trip.objects.create(
            parent=ride_request.parent,
            chauffeur=request.user,
            scheduled_date=ride_request.requested_pickup_time.date(),
            status='in_progress'
        )
        
        # Lier le trip à la demande de course
        ride_request.trip = trip
        ride_request.save()
        
        # Créer le premier checkpoint
        Checkpoint.objects.create(
            trip=trip,
            checkpoint_type='en_route',
            latitude=request.user.chauffeur_profile.current_latitude or 0,
            longitude=request.user.chauffeur_profile.current_longitude or 0,
            notes=f"Course acceptée par {request.user.get_full_name()}"
        )
        
        # Notifier le particulier avec lien vers la gestion de course
        notification_service.send_notification(
            user=ride_request.parent,
            title="✅ Course acceptée !",
            message=(
                f"{request.user.get_full_name()} a accepté votre demande de course.\n"
                f"Véhicule: {request.user.chauffeur_profile.vehicle_make} "
                f"{request.user.chauffeur_profile.vehicle_model}\n"
                f"Plaque: {request.user.chauffeur_profile.vehicle_plate}\n"
                f"Gérez votre course: /courses/particulier/{trip.id}/"
            ),
            notification_type="trip_accepted",
            channels=['in_app', 'push', 'email']
        )
        
        # Notifier les autres chauffeurs que la demande n'est plus disponible
        _cancel_pending_notifications(ride_request)
        
        return JsonResponse({
            'success': True,
            'message': 'Course acceptée ! Le tracking est maintenant actif.',
            'trip_id': trip.id,
            'trip_management_url': f'/courses/chauffeur/{trip.id}/',
            'parent_name': ride_request.parent.get_full_name() or ride_request.parent.username,
            'pickup_location': ride_request.pickup_location,
            'dropoff_location': ride_request.dropoff_location,
            'pickup_time': ride_request.requested_pickup_time.strftime('%H:%M')
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def decline_ride_request_advanced(request, pk):
    """
    Refus d'une demande de course.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    if request.user.role != UserRoles.CHAUFFEUR:
        return JsonResponse({'error': 'Seuls les chauffeurs peuvent refuser'}, status=403)
    
    try:
        ride_request = get_object_or_404(RideRequest, pk=pk, status='pending')
        
        # Marquer la demande comme refusée par ce chauffeur
        # Note: Dans un système complet, on créerait un modèle RideRequestResponse
        # Pour l'instant, on supprime juste la demande de la liste de ce chauffeur
        
        # Notifier le particulier du refus
        from core.notifications import notification_service
        
        notification_service.send_notification(
            user=ride_request.parent,
            title="Demande refusée",
            message=f"Un chauffeur a refusé votre demande. D'autres chauffeurs peuvent encore l'accepter.",
            notification_type="trip_update",
            channels=['in_app']
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Demande refusée. Le particulier a été notifié.'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def get_parent_ride_requests_status(request):
    """
    API pour que les particuliers puissent suivre leurs demandes en temps réel.
    """
    if request.user.role != UserRoles.PARENT:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    try:
        # Récupérer les demandes récentes du particulier
        cutoff_time = timezone.now() - timedelta(hours=4)  # Demandes des 4 dernières heures
        recent_cutoff = timezone.now() - timedelta(days=7)

        requests = RideRequest.objects.filter(
            parent=request.user,
            requested_at__gte=recent_cutoff,
            parent_archived=False,
        ).select_related('chauffeur', 'trip').order_by('-requested_at')[:10]
        
        requests_data = []
        for ride_request in requests:
            request_data = {
                'id': ride_request.id,
                'status': ride_request.status,
                'pickup_location': ride_request.pickup_location,
                'dropoff_location': ride_request.dropoff_location,
                'pickup_time': ride_request.requested_pickup_time.strftime('%H:%M'),
                'created_ago': (timezone.now() - ride_request.requested_at).total_seconds() // 60,
                'chauffeur_name': None,
                'trip_id': None,
                'tracking_url': None
            }
            
            if ride_request.chauffeur:
                request_data['chauffeur_name'] = ride_request.chauffeur.get_full_name() or ride_request.chauffeur.username
                
            if ride_request.trip:
                request_data['trip_id'] = ride_request.trip.id
                request_data['tracking_url'] = f'/subscriptions/tracking/{ride_request.trip.id}/'
            
            requests_data.append(request_data)
        
        return JsonResponse({
            'requests': requests_data,
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=500)


@login_required
def get_ride_requests_realtime(request):
    """
    API pour récupérer les demandes de course en temps réel (polling).
    
    Utilisé par les chauffeurs pour voir les nouvelles demandes
    sans recharger la page.
    """
    if request.user.role != UserRoles.CHAUFFEUR:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    try:
        # Récupérer les demandes en attente pour ce chauffeur
        # En production, filtrer par géolocalisation et critères
        
        # Récupérer les demandes en attente (incluant celles récentes même si l'heure est passée)
        cutoff_time = timezone.now() - timedelta(hours=2)  # Demandes des 2 dernières heures
        
        pending_requests = RideRequest.objects.filter(
            status='pending',
            requested_at__gte=cutoff_time  # Changé de requested_pickup_time à requested_at
        ).select_related('parent').order_by('-requested_at')[:10]
        
        requests_data = []
        for ride_request in pending_requests:
            # Calculer distance si possible
            distance = None
            if (ride_request.pickup_latitude and ride_request.pickup_longitude and
                request.user.chauffeur_profile.current_latitude and
                request.user.chauffeur_profile.current_longitude):
                
                distance = calculate_distance(
                    float(request.user.chauffeur_profile.current_latitude),
                    float(request.user.chauffeur_profile.current_longitude),
                    float(ride_request.pickup_latitude),
                    float(ride_request.pickup_longitude)
                )
            
            requests_data.append({
                'id': ride_request.id,
                'parent_name': ride_request.parent.get_full_name() or ride_request.parent.username,
                'pickup_location': ride_request.pickup_location,
                'dropoff_location': ride_request.dropoff_location,
                'pickup_time': ride_request.requested_pickup_time.strftime('%H:%M'),
                'notes': ride_request.notes,
                'distance_km': round(distance, 1) if distance else None,
                'created_ago': (timezone.now() - ride_request.requested_at).total_seconds() // 60,
                'accept_url': f'/subscriptions/ride-requests/{ride_request.id}/accept/',
                'decline_url': f'/subscriptions/ride-requests/{ride_request.id}/decline/'
            })
        
        return JsonResponse({
            'requests': requests_data,
            'timestamp': timezone.now().isoformat(),
            'chauffeur_available': request.user.chauffeur_profile.is_available
        })
        
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=500)


class ChauffeurRideRequestsRealtimeView(LoginRequiredMixin, TemplateView):
    """
    Vue pour les chauffeurs pour voir les demandes de course en temps réel.
    
    Affiche une interface avec polling automatique des nouvelles demandes,
    avec possibilité d'accepter/refuser directement depuis l'interface.
    """
    template_name = "subscriptions/chauffeur_ride_requests_modern.html"
    
    def dispatch(self, request, *args, **kwargs):
        """Vérifier que seuls les chauffeurs peuvent accéder."""
        if request.user.role != UserRoles.CHAUFFEUR:
            messages.error(request, "Seuls les chauffeurs peuvent accéder à cette page.")
            return redirect("core:dashboard")
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        """Ajouter les données nécessaires au template."""
        context = super().get_context_data(**kwargs)
        
        # Statut de disponibilité du chauffeur
        context['is_available'] = self.request.user.chauffeur_profile.is_available
        
        # Statistiques rapides
        context['total_requests_today'] = RideRequest.objects.filter(
            requested_at__date=timezone.now().date()
        ).count()
        
        context['accepted_today'] = RideRequest.objects.filter(
            chauffeur=self.request.user,
            status='accepted',
            responded_at__date=timezone.now().date()
        ).count()
        
        return context


class RideRequestWaitingView(LoginRequiredMixin, DetailView):
    """
    Vue d'attente montrant la liste des chauffeurs disponibles.
    
    Affiche les chauffeurs éligibles pendant que le particulier attend
    une réponse, avec mise à jour en temps réel du statut.
    """
    model = RideRequest
    template_name = "subscriptions/ride_request_waiting_cohesive.html"
    context_object_name = "ride_request"
    
    def dispatch(self, request, *args, **kwargs):
        """Vérifier que seuls les particuliers peuvent accéder à leurs propres demandes."""
        ride_request = self.get_object()
        
        if request.user.role != UserRoles.PARENT:
            messages.error(request, "Accès non autorisé.")
            return redirect("core:dashboard")
            
        if ride_request.parent != request.user:
            messages.error(request, "Cette demande ne vous appartient pas.")
            return redirect("core:dashboard")
            
        # Si la demande est déjà acceptée, rediriger vers le tracking
        if ride_request.status == 'accepted' and ride_request.trip:
            return redirect("subscriptions:trip_tracking", pk=ride_request.trip.pk)
            
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        """Ajouter la liste des chauffeurs éligibles au contexte."""
        context = super().get_context_data(**kwargs)
        ride_request = self.get_object()
        
        # Récupérer les chauffeurs éligibles avec distances
        eligible_chauffeurs = self._get_eligible_chauffeurs_with_details(ride_request)
        context['eligible_chauffeurs'] = eligible_chauffeurs
        
        return context
    
    def _get_eligible_chauffeurs_with_details(self, ride_request):
        """
        Récupère la liste des chauffeurs éligibles avec détails complets.
        """
        from core.utils import find_available_chauffeurs, calculate_distance, get_estimated_arrival_time
        
        eligible_chauffeurs = []
        
        if ride_request.pickup_latitude and ride_request.pickup_longitude:
            # Utiliser la géolocalisation pour trouver les chauffeurs
            chauffeur_profiles = find_available_chauffeurs(
                pickup_lat=float(ride_request.pickup_latitude),
                pickup_lon=float(ride_request.pickup_longitude),
                max_distance_km=ride_request.max_distance_km,
                min_reliability_score=float(ride_request.min_rating)
            )
            
            for profile in chauffeur_profiles:
                user = profile.user
                
                # Calculer la distance
                if (profile.current_latitude and profile.current_longitude):
                    distance = calculate_distance(
                        float(profile.current_latitude),
                        float(profile.current_longitude),
                        float(ride_request.pickup_latitude),
                        float(ride_request.pickup_longitude)
                    )
                    user.distance_km = distance
                    
                    # Calculer l'ETA
                    eta = get_estimated_arrival_time(
                        float(profile.current_latitude),
                        float(profile.current_longitude),
                        float(ride_request.pickup_latitude),
                        float(ride_request.pickup_longitude)
                    )
                    user.eta_minutes = int(eta.total_seconds() / 60)
                else:
                    user.distance_km = None
                    user.eta_minutes = None
                
                eligible_chauffeurs.append(user)
        else:
            # Fallback sans géolocalisation
            eligible_chauffeurs = list(User.objects.filter(
                role=UserRoles.CHAUFFEUR,
                is_active=True,
                chauffeur_profile__is_available=True,
                chauffeur_profile__reliability_score__gte=ride_request.min_rating
            ).select_related('chauffeur_profile', 'profile')[:5])
        
        # Trier selon la priorité
        if ride_request.priority == 'closest' and eligible_chauffeurs:
            eligible_chauffeurs.sort(key=lambda x: x.distance_km if hasattr(x, 'distance_km') and x.distance_km else float('inf'))
        elif ride_request.priority == 'best_rated':
            eligible_chauffeurs.sort(key=lambda x: x.chauffeur_profile.reliability_score, reverse=True)
        elif ride_request.priority == 'fastest' and eligible_chauffeurs:
            eligible_chauffeurs.sort(key=lambda x: x.eta_minutes if hasattr(x, 'eta_minutes') and x.eta_minutes else float('inf'))
        
        return eligible_chauffeurs[:5]  # Limiter à 5 chauffeurs max


@login_required
def ride_request_status_api(request, pk):
    """
    API pour vérifier le statut d'une demande de course en temps réel.
    """
    try:
        ride_request = get_object_or_404(RideRequest, pk=pk, parent=request.user)
        
        response_data = {
            'id': ride_request.id,
            'status': ride_request.status,
            'created_at': ride_request.requested_at.isoformat(),
        }
        
        if ride_request.status == 'accepted' and ride_request.chauffeur:
            response_data.update({
                'chauffeur_name': ride_request.chauffeur.get_full_name() or ride_request.chauffeur.username,
                'chauffeur_phone': ride_request.chauffeur.profile.phone if hasattr(ride_request.chauffeur, 'profile') else None,
                'tracking_url': f'/subscriptions/tracking/{ride_request.trip.id}/' if ride_request.trip else None,
            })
        
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)


@login_required
def cancel_ride_request_api(request, pk):
    """
    API pour annuler une demande de course.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    try:
        ride_request = get_object_or_404(RideRequest, pk=pk, parent=request.user)
        
        if ride_request.status != 'pending':
            return JsonResponse({
                'success': False,
                'error': 'Cette demande ne peut plus être annulée'
            })
        
        ride_request.status = 'cancelled'
        ride_request.responded_at = timezone.now()
        ride_request.save()
        
        # Notifier les chauffeurs que la demande est annulée
        from core.notifications import notification_service
        
        # En production, notifier tous les chauffeurs qui avaient reçu la demande
        eligible_chauffeurs = User.objects.filter(
            role=UserRoles.CHAUFFEUR,
            is_active=True,
            chauffeur_profile__is_available=True
        )[:5]  # Limiter pour éviter le spam
        
        for chauffeur in eligible_chauffeurs:
            notification_service.send_notification(
                user=chauffeur,
                title="Demande de course annulée",
                message=f"La demande de course vers {ride_request.dropoff_location} a été annulée.",
                notification_type="trip_update",
                channels=['in_app']
            )
        
        return JsonResponse({
            'success': True,
            'message': 'Demande annulée avec succès'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def delete_ride_request_api(request, pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})

    ride_request = get_object_or_404(RideRequest, pk=pk)

    if request.user == ride_request.parent or request.user == ride_request.chauffeur:
        ride_request.archive_for_user(request.user)
        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Accès refusé'}, status=403)


def _cancel_pending_notifications(accepted_request):
    """
    Annule les notifications en attente pour les autres chauffeurs
    quand une demande est acceptée.
    """
    # En production, implémenter un système de notification en temps réel
    # pour informer les autres chauffeurs que la demande n'est plus disponible
    
    # Pour l'instant, on peut juste créer une notification générale
    other_chauffeurs = User.objects.filter(
        role=UserRoles.CHAUFFEUR,
        is_active=True,
        chauffeur_profile__is_available=True
    ).exclude(id=accepted_request.chauffeur.id)
    
    for chauffeur in other_chauffeurs[:5]:  # Limiter pour éviter le spam
        notification_service.send_notification(
            user=chauffeur,
            title="Demande de course prise",
            message=f"La course vers {accepted_request.dropoff_location} a été acceptée par un autre chauffeur.",
            notification_type="trip_update",
            channels=['in_app']  # Notification discrète
        )


@login_required
def get_chauffeur_notifications(request):
    """
    API pour récupérer les notifications du chauffeur.
    """
    if request.user.role != UserRoles.CHAUFFEUR:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    try:
        from datetime import timedelta
        from core.models import NotificationLog
        
        # Récupérer les notifications récentes
        cutoff_time = timezone.now() - timedelta(hours=24)  # Dernières 24h
        
        notifications = NotificationLog.objects.filter(
            user=request.user,
            created_at__gte=cutoff_time
        ).order_by('-created_at')[:20]
        
        notifications_data = []
        for notif in notifications:
            notifications_data.append({
                'id': notif.id,
                'title': notif.title,
                'message': notif.message,
                'type': notif.notification_type,
                'created_at': notif.created_at.strftime('%H:%M'),
                'created_ago': (timezone.now() - notif.created_at).total_seconds() // 60,
                'is_read': notif.read
            })
        
        # Compter les non lues
        unread_count = len([n for n in notifications_data if not n['is_read']])
        
        return JsonResponse({
            'notifications': notifications_data,
            'unread_count': unread_count,
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=500)


@login_required
def toggle_chauffeur_availability(request):
    """
    API pour basculer la disponibilité du chauffeur.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    if request.user.role != UserRoles.CHAUFFEUR:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    try:
        import json
        data = json.loads(request.body)
        is_available = data.get('is_available', False)
        
        chauffeur_profile = request.user.chauffeur_profile
        chauffeur_profile.is_available = is_available
        chauffeur_profile.save()
        
        # Envoyer une notification au chauffeur
        from core.notifications import notification_service
        status_text = "disponible" if is_available else "indisponible"
        
        notification_service.send_notification(
            user=request.user,
            title=f"Statut mis à jour",
            message=f"Vous êtes maintenant {status_text} pour recevoir des demandes de course.",
            notification_type="status_update",
            channels=['in_app']
        )
        
        return JsonResponse({
            'success': True,
            'is_available': is_available,
            'message': f'Statut mis à jour: {status_text}'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def get_pending_requests_count(request):
    """
    API pour récupérer le nombre total de demandes en attente (courses + abonnements).
    """
    if request.user.role != UserRoles.CHAUFFEUR:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    try:
        from .models import ChauffeurSubscriptionRequest, SubscriptionRequestStatus
        
        # Compter les demandes de course en attente
        ride_requests_count = RideRequest.objects.filter(
            status=RideRequestStatus.PENDING
        ).exclude(
            chauffeur_archived=True
        ).count()
        
        # Compter les demandes d'abonnement en attente pour ce chauffeur
        subscription_requests_count = ChauffeurSubscriptionRequest.objects.filter(
            chauffeur=request.user,
            status=SubscriptionRequestStatus.PENDING
        ).count()
        
        total_count = ride_requests_count + subscription_requests_count
        
        return JsonResponse({
            'ride_requests_count': ride_requests_count,
            'subscription_requests_count': subscription_requests_count,
            'total_count': total_count,
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=500)


@login_required
def get_subscription_requests_realtime(request):
    """
    API pour récupérer les demandes d'abonnement en temps réel pour un chauffeur.
    """
    if request.user.role != UserRoles.CHAUFFEUR:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    try:
        from .models import ChauffeurSubscriptionRequest, SubscriptionRequestStatus
        
        # Récupérer les demandes d'abonnement en attente pour ce chauffeur
        subscription_requests = ChauffeurSubscriptionRequest.objects.filter(
            chauffeur=request.user,
            status=SubscriptionRequestStatus.PENDING
        ).select_related('parent').order_by('-created_at')
        
        requests_data = []
        for req in subscription_requests:
            requests_data.append({
                'id': req.id,
                'parent_name': req.parent.get_full_name() or req.parent.username,
                'parent_email': req.parent.email,
                'parent_phone': req.parent.phone if hasattr(req.parent, 'phone') else '',
                'title': req.title or 'Demande d\'abonnement',
                'description': req.description or '',
                'pickup_location': req.pickup_location or '',
                'dropoff_location': req.dropoff_location or '',
                'frequency': req.get_frequency_display() if hasattr(req, 'get_frequency_display') else req.frequency,
                'proposed_price': float(req.proposed_price) if req.proposed_price else 0,
                'created_at': req.created_at.strftime('%d/%m/%Y %H:%M'),
                'created_ago_minutes': int((timezone.now() - req.created_at).total_seconds() // 60),
            })
        
        return JsonResponse({
            'requests': requests_data,
            'count': len(requests_data),
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'requests': [],
            'count': 0,
            'timestamp': timezone.now().isoformat()
        }, status=500)
