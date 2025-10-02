"""
Vues pour l'application Subscriptions.

Ce fichier contient toutes les vues liées aux demandes de course,
au suivi GPS en temps réel, et à la gestion des trajets.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.template.loader import render_to_string
from django.db.models import Avg, Count, Sum, Q

from accounts.models import User, UserRoles
from core.models import NotificationLog
from core.utils import get_estimated_arrival_time, mock_gps_update
from .forms import RideRequestFilterForm, RideRequestForm
from .models import (
    RideRequest, RideRequestStatus, Trip, Checkpoint, Subscription, SubscriptionStatus,
    MobilityPlusSubscription, ChauffeurSubscriptionRequest, ChauffeurSubscription, 
    SubscriptionPayment, ChatMessage
)
from .utils import find_available_chauffeurs


class ParentRideRequestCreateView(LoginRequiredMixin, View):
    template_name = "subscriptions/ride_request_create.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.role != UserRoles.PARENT:
            messages.error(request, "Seuls les particuliers peuvent créer une demande de course.")
            return redirect("core:dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        form = RideRequestForm()
        available_chauffeurs = find_available_chauffeurs()
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "chauffeurs": available_chauffeurs,
            },
        )

    def post(self, request):
        form = RideRequestForm(request.POST)
        available_chauffeurs = find_available_chauffeurs()
        if form.is_valid():
            zone = form.cleaned_data.get("preferred_zone")
            chauffeur = find_available_chauffeurs(zone=zone).first() or available_chauffeurs.first()

            if chauffeur is None:
                messages.error(request, "Aucun chauffeur disponible pour le moment.")
                return render(request, self.template_name, {"form": form, "chauffeurs": available_chauffeurs})

            ride = RideRequest.objects.create(
                parent=request.user,
                chauffeur=chauffeur,
                pickup_location=form.cleaned_data["pickup_location"],
                dropoff_location=form.cleaned_data["dropoff_location"],
                requested_pickup_time=form.cleaned_data["requested_pickup_time"],
                notes=form.cleaned_data["notes"],
            )
            NotificationLog.objects.create(
                user=chauffeur,
                title="Nouvelle demande de course",
                message=f"{request.user.get_full_name() or request.user.username} vous a envoyé une demande.",
                notification_type="trip_update",
            )
            messages.success(request, "Demande envoyée. Le chauffeur peut maintenant accepter ou refuser.")
            return redirect("subscriptions:ride_requests_parent")

        return render(request, self.template_name, {"form": form, "chauffeurs": available_chauffeurs})


class TripTrackingView(LoginRequiredMixin, DetailView):
    """
    Vue pour le suivi GPS en temps réel d'une course.
    
    Affiche une carte interactive avec la position du chauffeur,
    les checkpoints de la course, et les informations en temps réel.
    """
    model = Trip
    template_name = "subscriptions/trip_tracking.html"
    context_object_name = "trip"
    
    def get_context_data(self, **kwargs):
        """
        Ajoute les données nécessaires pour le suivi GPS.
        """
        context = super().get_context_data(**kwargs)
        trip = self.get_object()
        
        # Récupérer tous les checkpoints de la course
        checkpoints = trip.checkpoints.all().order_by('timestamp')
        
        # Marquer le checkpoint actuel
        current_checkpoint = None
        for checkpoint in checkpoints:
            checkpoint.is_current = False
            if not checkpoint.completed_at and current_checkpoint is None:
                checkpoint.is_current = True
                current_checkpoint = checkpoint
        
        # Calculer l'ETA si possible
        estimated_arrival = None
        if (trip.chauffeur.chauffeur_profile.current_latitude and 
            trip.chauffeur.chauffeur_profile.current_longitude and
            trip.pickup_latitude and trip.pickup_longitude):
            
            estimated_arrival = get_estimated_arrival_time(
                float(trip.chauffeur.chauffeur_profile.current_latitude),
                float(trip.chauffeur.chauffeur_profile.current_longitude),
                float(trip.pickup_latitude),
                float(trip.pickup_longitude)
            )
        
        context.update({
            'checkpoints': checkpoints,
            'current_checkpoint': current_checkpoint,
            'estimated_arrival': estimated_arrival or 'N/A',
        })
        
        return context


@login_required
def trip_location_api(request, trip_id):
    """
    API pour récupérer la position actuelle du chauffeur.
    
    Retourne les coordonnées GPS du chauffeur et l'ETA estimé
    au format JSON pour les mises à jour en temps réel.
    """
    try:
        trip = get_object_or_404(Trip, id=trip_id)
        
        # Vérifier que l'utilisateur a le droit de voir cette course
        if (request.user != trip.parent and 
            request.user != trip.chauffeur and 
            not request.user.is_staff):
            return JsonResponse({'error': 'Accès non autorisé'}, status=403)
        
        chauffeur_profile = trip.chauffeur.chauffeur_profile
        
        # Simuler une mise à jour GPS (en production, cela viendrait d'une vraie API)
        if trip.status == 'in_progress' and trip.pickup_latitude and trip.pickup_longitude:
            mock_gps_update(
                chauffeur_profile,
                float(trip.pickup_latitude),
                float(trip.pickup_longitude)
            )
        
        data = {
            'latitude': float(chauffeur_profile.current_latitude) if chauffeur_profile.current_latitude else None,
            'longitude': float(chauffeur_profile.current_longitude) if chauffeur_profile.current_longitude else None,
            'last_update': timezone.now().isoformat(),
        }
        
        # Calculer l'ETA si possible
        if (data['latitude'] and data['longitude'] and 
            trip.pickup_latitude and trip.pickup_longitude):
            eta = get_estimated_arrival_time(
                data['latitude'], data['longitude'],
                float(trip.pickup_latitude), float(trip.pickup_longitude)
            )
            data['eta_minutes'] = eta
        
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def trip_checkpoints_api(request, trip_id):
    """
    API pour récupérer les checkpoints d'une course.
    
    Retourne la liste des étapes de la course avec leur statut
    au format JSON pour les mises à jour en temps réel.
    """
    try:
        trip = get_object_or_404(Trip, id=trip_id)
        
        # Vérifier les permissions
        if (request.user != trip.parent and 
            request.user != trip.chauffeur and 
            not request.user.is_staff):
            return JsonResponse({'error': 'Accès non autorisé'}, status=403)
        
        checkpoints = trip.checkpoints.all().order_by('created_at')
        
        data = []
        for checkpoint in checkpoints:
            data.append({
                'id': checkpoint.id,
                'type': checkpoint.checkpoint_type,
                'type_display': checkpoint.get_checkpoint_type_display(),
                'completed_at': checkpoint.completed_at.isoformat() if checkpoint.completed_at else None,
                'latitude': float(checkpoint.latitude) if checkpoint.latitude else None,
                'longitude': float(checkpoint.longitude) if checkpoint.longitude else None,
                'notes': checkpoint.notes,
            })
        
        return JsonResponse({'checkpoints': data})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def update_chauffeur_location(request):
    """
    API pour que les chauffeurs mettent à jour leur position GPS.
    
    Permet aux chauffeurs de signaler leur position actuelle
    via une requête POST avec latitude et longitude.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    if request.user.role != UserRoles.CHAUFFEUR:
        return JsonResponse({'error': 'Seuls les chauffeurs peuvent mettre à jour leur position'}, status=403)
    
    try:
        import json
        data = json.loads(request.body)
        
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        
        if not latitude or not longitude:
            return JsonResponse({'error': 'Latitude et longitude requises'}, status=400)
        
        # Mettre à jour la position du chauffeur
        chauffeur_profile = request.user.chauffeur_profile
        chauffeur_profile.current_latitude = latitude
        chauffeur_profile.current_longitude = longitude
        chauffeur_profile.save(update_fields=['current_latitude', 'current_longitude'])
        
        return JsonResponse({
            'success': True,
            'message': 'Position mise à jour',
            'latitude': latitude,
            'longitude': longitude,
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def create_checkpoint(request, trip_id):
    """
    API pour créer un nouveau checkpoint dans une course.
    
    Permet aux chauffeurs de signaler les étapes importantes
    de leur course (arrivé, passager récupéré, etc.).
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    try:
        trip = get_object_or_404(Trip, id=trip_id)
        
        # Vérifier que c'est le bon chauffeur
        if request.user != trip.chauffeur:
            return JsonResponse({'error': 'Seul le chauffeur de cette course peut créer des checkpoints'}, status=403)
        
        import json
        data = json.loads(request.body)
        
        checkpoint_type = data.get('type')
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        notes = data.get('notes', '')
        
        if not checkpoint_type:
            return JsonResponse({'error': 'Type de checkpoint requis'}, status=400)
        
        # Créer le checkpoint
        checkpoint = Checkpoint.objects.create(
            trip=trip,
            checkpoint_type=checkpoint_type,
            latitude=latitude,
            longitude=longitude,
            notes=notes,
            completed_at=timezone.now()
        )
        
        # Envoyer une notification au parent
        NotificationLog.objects.create(
            user=trip.parent,
            title=f"Étape: {checkpoint.get_checkpoint_type_display()}",
            message=f"Votre chauffeur a signalé: {checkpoint.get_checkpoint_type_display()}",
            notification_type="trip_update",
        )
        
        return JsonResponse({
            'success': True,
            'checkpoint': {
                'id': checkpoint.id,
                'type': checkpoint.checkpoint_type,
                'type_display': checkpoint.get_checkpoint_type_display(),
                'completed_at': checkpoint.completed_at.isoformat(),
                'notes': checkpoint.notes,
            }
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


class TripHistoryView(LoginRequiredMixin, ListView):
    """
    Vue pour l'historique détaillé des courses avec statistiques.
    
    Affiche l'historique complet des courses d'un utilisateur avec :
    - Statistiques générales (nombre de courses, distance, notes)
    - Graphiques d'évolution
    - Filtres par statut et période
    - Détails de chaque course
    """
    model = Trip
    template_name = "subscriptions/trip_history.html"
    context_object_name = "trips"
    paginate_by = 20
    
    def get_queryset(self):
        user = self.request.user
        recent_cutoff = timezone.now() - timezone.timedelta(days=7)

        if user.role == UserRoles.PARENT:
            queryset = Trip.objects.filter(parent=user, parent_archived=False)
        elif user.role == UserRoles.CHAUFFEUR:
            queryset = Trip.objects.filter(chauffeur=user, chauffeur_archived=False)
        else:
            queryset = Trip.objects.all()

        queryset = queryset.filter(scheduled_date__gte=recent_cutoff.date())

        status_filter = self.request.GET.get('status')
        if status_filter:
            if ',' in status_filter:
                statuses = [s.strip() for s in status_filter.split(',')]
                queryset = queryset.filter(status__in=statuses)
            else:
                queryset = queryset.filter(status=status_filter)

        return queryset.select_related('parent', 'chauffeur').order_by('-scheduled_date')
    
    def get_context_data(self, **kwargs):
        """
        Ajoute les statistiques et données pour les graphiques.
        """
        import json
        
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['is_archived_for_user'] = lambda trip: trip.is_archived_for(user)
        
        # Récupérer toutes les courses pour les stats
        all_trips = self.get_queryset()
        
        # Calculer les statistiques générales
        stats = self._calculate_stats(all_trips)
        context['stats'] = stats
        
        # Données pour les graphiques
        monthly_data = self._get_monthly_data(all_trips)
        status_data = self._get_status_data(all_trips)
        
        context['monthly_data'] = json.dumps(monthly_data)
        context['status_data'] = json.dumps(status_data)
        
        return context
    
    def _calculate_stats(self, trips):
        """
        Calcule les statistiques générales.
        """
        from django.db.models import Avg, Sum, Count
        
        total_trips = trips.count()
        completed_trips = trips.filter(status='completed').count()
        
        # Distance totale
        total_distance = trips.aggregate(
            total=Sum('distance_km')
        )['total'] or 0
        
        # Note moyenne
        avg_rating = trips.filter(
            rating__isnull=False
        ).aggregate(
            avg=Avg('rating__score')
        )['avg'] or 0
        
        return {
            'total_trips': total_trips,
            'completed_trips': completed_trips,
            'cancelled_trips': trips.filter(status='cancelled').count(),
            'success_rate': (completed_trips / total_trips * 100) if total_trips > 0 else 0,
            'total_distance': total_distance,
            'avg_distance': (total_distance / completed_trips) if completed_trips > 0 else 0,
            'avg_rating': avg_rating,
        }
    
    def _get_monthly_data(self, trips):
        """
        Prépare les données pour le graphique mensuel.
        """
        from django.db.models import Count
        from django.db.models.functions import TruncMonth
        from datetime import datetime, timedelta
        
        # Dernières 12 mois
        end_date = timezone.now()
        start_date = end_date - timedelta(days=365)
        
        monthly_trips = trips.filter(
            scheduled_date__gte=start_date
        ).annotate(
            month=TruncMonth('scheduled_date')
        ).values('month').annotate(
            count=Count('id')
        ).order_by('month')
        
        # Créer les labels et données
        labels = []
        data = []
        
        for item in monthly_trips:
            labels.append(item['month'].strftime('%b %Y'))
            data.append(item['count'])
        
        return {
            'labels': labels,
            'data': data
        }
    
    def _get_status_data(self, trips):
        """
        Prépare les données pour le graphique de répartition par statut.
        """
        from django.db.models import Count
        
        status_counts = trips.values('status').annotate(
            count=Count('id')
        ).order_by('-count')
        
        labels = []
        data = []
        
        status_labels = {
            'completed': 'Terminées',
            'cancelled': 'Annulées',
            'in_progress': 'En cours',
            'pending': 'En attente'
        }
        
        for item in status_counts:
            labels.append(status_labels.get(item['status'], item['status'].title()))
            data.append(item['count'])
        
        return {
            'labels': labels,
            'data': data
        }


@login_required
def trip_details_api(request, trip_id):
    """
    API pour récupérer les détails complets d'une course.
    
    Retourne toutes les informations d'une course : trajet, chauffeur,
    checkpoints, évaluation, etc. pour l'affichage dans le modal.
    """
    try:
        trip = get_object_or_404(Trip, id=trip_id)
        
        # Vérifier les permissions
        if (request.user != trip.parent and 
            request.user != trip.chauffeur and 
            not request.user.is_staff):
            return JsonResponse({'error': 'Accès non autorisé'}, status=403)
        
        # Informations du chauffeur
        chauffeur_data = {
            'name': trip.chauffeur.get_full_name() if trip.chauffeur else 'N/A',
            'vehicle': f"{trip.chauffeur.chauffeur_profile.vehicle_make} {trip.chauffeur.chauffeur_profile.vehicle_model}" if trip.chauffeur else 'N/A',
            'plate': trip.chauffeur.chauffeur_profile.vehicle_plate if trip.chauffeur else 'N/A',
            'rating': trip.chauffeur.chauffeur_profile.reliability_score if trip.chauffeur else 0,
        }
        
        # Checkpoints de la course
        checkpoints_data = []
        for checkpoint in trip.checkpoints.all().order_by('created_at'):
            checkpoints_data.append({
                'type': checkpoint.checkpoint_type,
                'type_display': checkpoint.get_checkpoint_type_display(),
                'time': checkpoint.completed_at.strftime('%H:%M') if checkpoint.completed_at else 'N/A',
                'notes': checkpoint.notes
            })
        
        # Évaluation
        rating_data = None
        if hasattr(trip, 'rating') and trip.rating:
            rating_data = {
                'score': trip.rating.score,
                'comment': trip.rating.comment
            }
        
        data = {
            'id': trip.id,
            'date': trip.scheduled_date.strftime('%d/%m/%Y'),
            'time': trip.scheduled_date.strftime('%H:%M'),
            'status': trip.status,
            'status_display': trip.get_status_display(),
            'pickup': trip.pickup_location or 'Point de départ',
            'dropoff': trip.dropoff_location or 'Destination',
            'distance': trip.distance_km,
            'duration': trip.duration_minutes,
            'chauffeur': chauffeur_data,
            'checkpoints': checkpoints_data,
            'rating': rating_data,
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def export_trip_history(request):
    """
    Exporte l'historique des courses au format CSV ou PDF.
    
    Permet aux utilisateurs de télécharger leur historique complet
    pour leurs archives personnelles ou comptables.
    """
    import csv
    from django.http import HttpResponse
    
    user = request.user
    format_type = request.GET.get('format', 'csv')
    
    # Récupérer les courses
    if user.role == UserRoles.PARENT:
        trips = Trip.objects.filter(parent=user)
    elif user.role == UserRoles.CHAUFFEUR:
        trips = Trip.objects.filter(chauffeur=user)
    else:
        trips = Trip.objects.all()
    
    trips = trips.select_related('parent', 'chauffeur', 'rating').order_by('-scheduled_date')
    
    if format_type == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="historique_courses_{user.username}.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Date', 'Heure', 'Départ', 'Arrivée', 'Chauffeur', 
            'Véhicule', 'Distance (km)', 'Durée (min)', 'Statut', 'Note'
        ])
        
        for trip in trips:
            writer.writerow([
                trip.scheduled_date.strftime('%d/%m/%Y'),
                trip.scheduled_date.strftime('%H:%M'),
                trip.pickup_location or '',
                trip.dropoff_location or '',
                trip.chauffeur.get_full_name() if trip.chauffeur else '',
                f"{trip.chauffeur.chauffeur_profile.vehicle_make} {trip.chauffeur.chauffeur_profile.vehicle_model}" if trip.chauffeur else '',
                trip.distance_km or '',
                trip.duration_minutes or '',
                trip.get_status_display(),
                trip.rating.score if hasattr(trip, 'rating') and trip.rating else ''
            ])
        
        return response


@login_required
def delete_subscription(request, subscription_id):
    """
    Supprimer un abonnement (ancien système).
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    try:
        subscription = get_object_or_404(Subscription, id=subscription_id)
        
        # Vérifier les permissions
        if request.user.role == UserRoles.PARENT and subscription.parent != request.user:
            return JsonResponse({'success': False, 'error': 'Accès refusé'})
        elif request.user.role == UserRoles.CHAUFFEUR and subscription.chauffeur != request.user:
            return JsonResponse({'success': False, 'error': 'Accès refusé'})
        elif request.user.role not in [UserRoles.PARENT, UserRoles.CHAUFFEUR, UserRoles.ADMIN]:
            return JsonResponse({'success': False, 'error': 'Accès refusé'})
        
        # Marquer comme annulé au lieu de supprimer
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.notes = f"Annulé par {request.user.get_full_name()} le {timezone.now().strftime('%d/%m/%Y à %H:%M')}"
        subscription.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Abonnement annulé avec succès'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


# === NOUVEAU SYSTÈME D'ABONNEMENTS ===

class NewSubscriptionSystemView(LoginRequiredMixin, TemplateView):
    """
    Vue principale pour le nouveau système d'abonnements.
    Gère les deux types : Mobility Plus et Abonnements Chauffeur.
    """
    template_name = 'subscriptions/new_subscription_system.html'
    
    def post(self, request, *args, **kwargs):
        """Gérer les demandes d'abonnement chauffeur."""
        if request.user.role != UserRoles.PARENT:
            return JsonResponse({'success': False, 'error': 'Accès refusé'})
        
        try:
            # Récupérer les données du formulaire
            chauffeur_id = request.POST.get('chauffeur')
            title = request.POST.get('title')
            description = request.POST.get('description', '')
            pickup_location = request.POST.get('pickup_location')
            dropoff_location = request.POST.get('dropoff_location')
            pickup_time = request.POST.get('pickup_time')
            return_time = request.POST.get('return_time')
            frequency = request.POST.get('frequency')
            proposed_price = request.POST.get('proposed_price_monthly')
            child_name = request.POST.get('child_name', '')
            special_requirements = request.POST.get('special_requirements', '')
            
            # Validation
            if not all([chauffeur_id, title, pickup_location, dropoff_location, pickup_time, proposed_price]):
                return JsonResponse({
                    'success': False,
                    'error': 'Tous les champs obligatoires doivent être remplis'
                })
            
            chauffeur = get_object_or_404(User, id=chauffeur_id, role=UserRoles.CHAUFFEUR)

            # Empêcher les doublons de demandes actives pour ce chauffeur
            if ChauffeurSubscriptionRequest.objects.filter(
                parent=request.user,
                chauffeur=chauffeur,
                status__in=[
                    ChauffeurSubscriptionRequest.PENDING,
                    ChauffeurSubscriptionRequest.PAYMENT_PENDING,
                    ChauffeurSubscriptionRequest.ACCEPTED,
                    ChauffeurSubscriptionRequest.ACTIVE,
                ],
            ).exists():
                return JsonResponse({
                    'success': False,
                    'error': "Une demande est déjà en cours avec ce chauffeur."
                })

            # Créer la demande d'abonnement
            subscription_request = ChauffeurSubscriptionRequest.objects.create(
                parent=request.user,
                chauffeur=chauffeur,
                title=title,
                description=description,
                pickup_location=pickup_location,
                dropoff_location=dropoff_location,
                pickup_time=pickup_time,
                return_time=return_time if return_time else None,
                frequency=frequency,
                proposed_price_monthly=Decimal(proposed_price),
                child_name=child_name,
                special_requirements=special_requirements,
                expires_at=timezone.now() + timedelta(days=7)
            )
            
            # TODO: Envoyer notification au chauffeur
            
            return JsonResponse({
                'success': True,
                'message': f'Votre demande a été envoyée à {chauffeur.get_full_name()}',
                'redirect_url': '/subscriptions/'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Récupérer l'abonnement Mobility Plus s'il existe
        try:
            mobility_plus = user.mobility_plus_subscription
            context['has_mobility_plus'] = mobility_plus.is_active and mobility_plus.status == 'active'
            context['mobility_plus'] = mobility_plus
        except:
            context['has_mobility_plus'] = False
            context['mobility_plus'] = None
        
        if user.role == UserRoles.PARENT:
            # Abonnements chauffeur actifs
            try:
                chauffeur_subscriptions = ChauffeurSubscription.objects.filter(
                    parent=user,
                    status='active'
                ).select_related('chauffeur')
                pending_requests = ChauffeurSubscriptionRequest.objects.filter(
                    parent=user,
                    status='pending',
                    responded_at__isnull=True,
                    created_at__gte=timezone.now() - timezone.timedelta(days=7)
                ).select_related('chauffeur')
                
                # Chauffeurs disponibles
                chauffeurs_available = User.objects.filter(
                    role=UserRoles.CHAUFFEUR,
                    is_active=True
                ).select_related('chauffeur_profile')
                
                context.update({
                    'chauffeur_subscriptions': chauffeur_subscriptions,
                    'pending_requests': pending_requests,
                    'chauffeurs_available': chauffeurs_available
                })
            except:
                context.update({
                    'chauffeur_subscriptions': [],
                    'pending_requests': [],
                    'chauffeurs_available': []
                })
        
        elif user.role == UserRoles.CHAUFFEUR:
            try:
                # Demandes reçues
                received_requests = ChauffeurSubscriptionRequest.objects.filter(
                    chauffeur=user,
                    status='pending',
                    responded_at__isnull=True,
                    created_at__gte=timezone.now() - timezone.timedelta(days=7)
                ).select_related('parent')
                
                # Clients actifs
                active_clients = ChauffeurSubscription.objects.filter(
                    chauffeur=user,
                    status='active'
                ).select_related('parent')
                
                context.update({
                    'received_requests': received_requests,
                    'active_clients': active_clients
                })
            except:
                context.update({
                    'received_requests': [],
                    'active_clients': []
                })
        
        return context


@login_required
def mobility_plus_subscribe(request):
    """
    Vue pour s'abonner à Mobility Plus.
    """
    if request.method == 'POST':
        # Vérifier si l'utilisateur a déjà un abonnement Mobility Plus ACTIF
        try:
            existing = request.user.mobility_plus_subscription
            if existing.is_active and existing.status == 'active':
                return JsonResponse({
                    'success': False,
                    'error': 'Vous avez déjà un abonnement Mobility Plus actif'
                })
            # Si l'abonnement existe mais n'est pas actif, on peut le réactiver
        except:
            pass
        
        try:
            # Créer ou réactiver l'abonnement Mobility Plus
            try:
                mobility_plus = request.user.mobility_plus_subscription
                # Réactiver un abonnement existant
                mobility_plus.next_billing_date = timezone.now().date() + timedelta(days=30)
                mobility_plus.is_active = False  # Sera activé après paiement
                mobility_plus.status = 'pending'  # Statut en attente de paiement
                mobility_plus.save()
            except:
                # Créer un nouvel abonnement
                mobility_plus = MobilityPlusSubscription.objects.create(
                    user=request.user,
                    next_billing_date=timezone.now().date() + timedelta(days=30),
                    is_active=False,  # Sera activé après paiement
                    status='pending'  # Statut en attente de paiement
                )
            
            # Créer le paiement
            payment = SubscriptionPayment.objects.create(
                payment_type='mobility_plus',
                mobility_plus_subscription=mobility_plus,
                user=request.user,
                amount=mobility_plus.price_monthly,
                payment_method='pending',
                description=f"Abonnement Mobility Plus - {request.user.get_full_name()}"
            )
            
            return JsonResponse({
                'success': True,
                'payment_id': payment.id,
                'redirect_url': reverse('subscriptions:payment_page', kwargs={'payment_id': payment.id})
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


@login_required
def mobility_plus_unsubscribe(request):
    """
    Vue pour se désabonner de Mobility Plus.
    """
    if request.method == 'POST':
        try:
            # Vérifier si l'utilisateur a un abonnement Mobility Plus
            try:
                mobility_plus = request.user.mobility_plus_subscription
            except:
                return JsonResponse({
                    'success': False,
                    'error': 'Vous n\'avez pas d\'abonnement Mobility Plus'
                })
            
            # Désactiver l'abonnement (peu importe son statut actuel)
            mobility_plus.is_active = False
            mobility_plus.status = 'cancelled'
            mobility_plus.end_date = timezone.now().date()
            mobility_plus.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Vous avez été désabonné de Mobility Plus avec succès'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


@login_required
def mobility_plus_activate(request):
    """
    Vue pour activer manuellement un abonnement Mobility Plus (pour les tests).
    """
    if request.method == 'POST':
        try:
            # Vérifier si l'utilisateur a un abonnement Mobility Plus
            try:
                mobility_plus = request.user.mobility_plus_subscription
            except:
                return JsonResponse({
                    'success': False,
                    'error': 'Vous n\'avez pas d\'abonnement Mobility Plus'
                })
            
            # Activer l'abonnement
            mobility_plus.is_active = True
            mobility_plus.status = 'active'
            mobility_plus.last_payment_date = timezone.now().date()
            mobility_plus.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Votre abonnement Mobility Plus a été activé avec succès'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


class PaymentPageView(LoginRequiredMixin, DetailView):
    """
    Page de paiement unifiée.
    """
    model = SubscriptionPayment
    template_name = 'subscriptions/payment_page.html'
    context_object_name = 'payment'
    pk_url_kwarg = 'payment_id'
    
    def get_queryset(self):
        return SubscriptionPayment.objects.filter(
            user=self.request.user,
            status='pending'
        )


@login_required
def chauffeur_respond_to_request(request, request_id):
    """
    Vue pour que le chauffeur réponde à une demande d'abonnement.
    """
    if request.user.role != UserRoles.CHAUFFEUR:
        return JsonResponse({'success': False, 'error': 'Accès refusé'})
    
    subscription_request = get_object_or_404(
        ChauffeurSubscriptionRequest,
        id=request_id,
        chauffeur=request.user,
        status='pending'
    )
    
    if request.method == 'POST':
        action = request.POST.get('action')
        response_message = request.POST.get('response_message', '')
        counter_offer = request.POST.get('counter_offer')
        
        if action == 'accept':
            # Accepter la demande
            final_price = Decimal(counter_offer) if counter_offer else subscription_request.proposed_price_monthly
            
            # Créer l'abonnement en attente de paiement
            chauffeur_subscription = ChauffeurSubscription.objects.create(
                subscription_request=subscription_request,
                parent=subscription_request.parent,
                chauffeur=subscription_request.chauffeur,
                title=subscription_request.title,
                pickup_location=subscription_request.pickup_location,
                dropoff_location=subscription_request.dropoff_location,
                pickup_time=subscription_request.pickup_time,
                return_time=subscription_request.return_time,
                frequency=subscription_request.frequency,
                price_monthly=final_price,
                child_name=subscription_request.child_name,
                special_requirements=subscription_request.special_requirements,
                status='payment_pending'
            )
            
            # Créer le paiement
            payment = SubscriptionPayment.objects.create(
                payment_type='chauffeur_subscription',
                chauffeur_subscription=chauffeur_subscription,
                user=subscription_request.parent,
                amount=final_price,
                payment_method='pending',
                description=f"Abonnement avec {subscription_request.chauffeur.get_full_name()}"
            )
            
            # Mettre à jour la demande
            subscription_request.status = 'accepted'
            subscription_request.responded_at = timezone.now()
            subscription_request.chauffeur_response = response_message
            if counter_offer:
                subscription_request.chauffeur_counter_offer = final_price
            subscription_request.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Demande acceptée. Le particulier sera notifié.',
                'payment_url': f'/subscriptions/payment/{payment.id}/'
            })
            
        elif action == 'reject':
            # Refuser la demande
            subscription_request.status = 'rejected'
            subscription_request.responded_at = timezone.now()
            subscription_request.chauffeur_response = response_message
            subscription_request.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Demande refusée. Le particulier sera notifié.'
            })
    
    return JsonResponse({'success': False, 'error': 'Action non valide'})


@login_required
def process_payment(request, payment_id):
    """
    Traiter un paiement (simulation MVP).
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    payment = get_object_or_404(
        SubscriptionPayment,
        id=payment_id,
        user=request.user,
        status='pending'
    )
    
    payment_method = request.POST.get('payment_method', 'mobile_money')
    
    try:
        # Simulation du paiement réussi
        payment.payment_method = payment_method
        payment.transaction_id = f"TXN_{timezone.now().timestamp():.0f}"
        payment.status = 'completed'
        payment.paid_at = timezone.now()
        payment.save()
        
        # Activer l'abonnement correspondant
        if payment.mobility_plus_subscription:
            payment.mobility_plus_subscription.is_active = True
            payment.mobility_plus_subscription.status = 'active'
            payment.mobility_plus_subscription.last_payment_date = timezone.now().date()
            payment.mobility_plus_subscription.save()
            
        elif payment.chauffeur_subscription:
            payment.chauffeur_subscription.status = 'active'
            payment.chauffeur_subscription.start_date = timezone.now().date()
            payment.chauffeur_subscription.next_billing_date = timezone.now().date() + timedelta(days=30)
            payment.chauffeur_subscription.save()
        
        subscription_type = "Mobility Plus" if payment.payment_type == 'mobility_plus' else "Abonnement Chauffeur"
        
        return JsonResponse({
            'success': True,
            'message': f'Paiement réussi ! Votre {subscription_type} est maintenant actif.',
            'redirect_url': '/subscriptions/new-system/'
        })
        
    except Exception as e:
        payment.status = 'failed'
        payment.save()
        return JsonResponse({
            'success': False,
            'error': 'Erreur lors du traitement du paiement'
        })


class ParentRideRequestListView(LoginRequiredMixin, ListView):
    template_name = "subscriptions/ride_request_parent_list.html"
    context_object_name = "ride_requests"

    def get_queryset(self):
        return RideRequest.objects.filter(parent=self.request.user).select_related("chauffeur", "trip")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = RideRequestFilterForm(self.request.GET)
        qs = context["ride_requests"]
        status = self.request.GET.get("status")
        if status:
            context["ride_requests"] = qs.filter(status=status)
        return context


class ParentRideRequestDetailView(LoginRequiredMixin, DetailView):
    template_name = "subscriptions/ride_request_parent_detail.html"
    context_object_name = "ride_request"

    def get_queryset(self):
        return RideRequest.objects.filter(parent=self.request.user).select_related("chauffeur", "trip")


class ChauffeurRideRequestInboxView(LoginRequiredMixin, ListView):
    template_name = "subscriptions/ride_request_chauffeur_list.html"
    context_object_name = "ride_requests"

    def dispatch(self, request, *args, **kwargs):
        if request.user.role != UserRoles.CHAUFFEUR:
            messages.error(request, "Réservé aux chauffeurs.")
            return redirect("core:dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return RideRequest.objects.filter(chauffeur=self.request.user, status__in=[RideRequestStatus.PENDING, RideRequestStatus.ACCEPTED]).select_related("parent", "trip")


@login_required
def chauffeur_ride_request_action(request, pk, action):
    ride_request = get_object_or_404(RideRequest, pk=pk, chauffeur=request.user)
    if ride_request.status != RideRequestStatus.PENDING:
        messages.warning(request, "Cette demande a déjà été traitée.")
        return redirect("subscriptions:ride_requests_chauffeur")

    if action == "accept":
        trip = ride_request.accept()
        if trip:
            NotificationLog.objects.create(
                user=ride_request.parent,
                title="Course acceptée",
                message="Votre chauffeur a accepté la demande.",
                notification_type="trip_update",
                sent_via_email=True,
            )
            messages.success(request, "Course acceptée. Début du suivi.")
    elif action == "decline":
        ride_request.decline()
        NotificationLog.objects.create(
            user=ride_request.parent,
            title="Course refusée",
            message="Le chauffeur a refusé la demande.",
            notification_type="trip_update",
            sent_via_email=True,
        )
        messages.info(request, "Demande refusée.")
    else:
        messages.error(request, "Action non reconnue.")

    return redirect("subscriptions:ride_requests_chauffeur")


@login_required
def trip_details_ajax(request, trip_id):
    """
    Vue AJAX pour récupérer les détails d'une course.
    """
    try:
        trip = get_object_or_404(Trip, id=trip_id)
        
        # Vérifier que l'utilisateur a accès à cette course
        if request.user.role == UserRoles.PARENT and trip.parent != request.user:
            return JsonResponse({'success': False, 'error': 'Accès refusé'})
        elif request.user.role == UserRoles.CHAUFFEUR and trip.chauffeur != request.user:
            return JsonResponse({'success': False, 'error': 'Accès refusé'})
        elif request.user.role not in [UserRoles.PARENT, UserRoles.CHAUFFEUR, UserRoles.ADMIN]:
            return JsonResponse({'success': False, 'error': 'Accès refusé'})
        
        # Récupérer les checkpoints de la course
        checkpoints = trip.checkpoints.all().order_by('timestamp')
        
        # Calculer les statistiques
        duration = None
        if trip.started_at and trip.completed_at:
            duration = trip.completed_at - trip.started_at
        
        # Rendu du template
        html = render_to_string('subscriptions/trip_details_modal.html', {
            'trip': trip,
            'checkpoints': checkpoints,
            'duration': duration,
            'user': request.user,
        })
        
        return JsonResponse({
            'success': True,
            'html': html
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def export_trip_history(request):
    """
    Vue pour exporter l'historique des courses en CSV.
    """
    import csv
    from datetime import datetime
    
    # Filtrer les courses selon le rôle de l'utilisateur
    if request.user.role == UserRoles.PARENT:
        trips = Trip.objects.filter(parent=request.user)
    elif request.user.role == UserRoles.CHAUFFEUR:
        trips = Trip.objects.filter(chauffeur=request.user)
    else:
        trips = Trip.objects.all()
    
    trips = trips.select_related('parent', 'chauffeur').order_by('-scheduled_date')
    
    # Créer la réponse CSV
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="historique_courses_{datetime.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    
    # En-têtes
    headers = [
        'Date',
        'Heure',
        'Particulier',
        'Chauffeur',
        'Départ',
        'Destination',
        'Distance (km)',
        'Durée (min)',
        'Statut',
        'Note'
    ]
    writer.writerow(headers)
    
    # Données
    for trip in trips:
        row = [
            trip.scheduled_date.strftime('%d/%m/%Y') if trip.scheduled_date else '',
            trip.started_at.strftime('%H:%M') if trip.started_at else '',
            trip.parent.get_full_name() if trip.parent else '',
            trip.chauffeur.get_full_name() if trip.chauffeur else '',
            getattr(trip, 'pickup_location', 'N/A'),
            getattr(trip, 'dropoff_location', 'N/A'),
            f"{trip.distance_km:.1f}" if hasattr(trip, 'distance_km') and trip.distance_km else '',
            str(trip.duration_minutes) if hasattr(trip, 'duration_minutes') and trip.duration_minutes else '',
            trip.get_status_display(),
            f"{trip.rating.score}/5" if hasattr(trip, 'rating') and trip.rating else ''
        ]
        writer.writerow(row)
    
    return response


# === VUES POUR LE CHAT ===

@login_required
def chat_list(request):
    """Liste des conversations de chat."""
    user = request.user
    
    # Récupérer les conversations (messages envoyés et reçus)
    sent_messages = ChatMessage.objects.filter(sender=user).values_list('recipient', flat=True).distinct()
    received_messages = ChatMessage.objects.filter(recipient=user).values_list('sender', flat=True).distinct()
    
    # Combiner et dédupliquer
    conversation_users = set(sent_messages) | set(received_messages)
    conversations = []
    
    for user_id in conversation_users:
        other_user = User.objects.get(id=user_id)
        last_message = ChatMessage.objects.filter(
            Q(sender=user, recipient=other_user) | 
            Q(sender=other_user, recipient=user)
        ).order_by('-created_at').first()
        
        conversations.append({
            'user': other_user,
            'last_message': last_message,
            'unread_count': ChatMessage.objects.filter(
                sender=other_user, 
                recipient=user, 
                is_read=False
            ).count()
        })
    
    # Trier par dernier message
    conversations.sort(key=lambda x: x['last_message'].created_at if x['last_message'] else timezone.now(), reverse=True)
    
    context = {
        'conversations': conversations,
        'user_has_mobility_plus': user_has_mobility_plus(user)
    }
    
    return render(request, 'subscriptions/chat_list.html', context)


@login_required
def chat_detail(request, user_id):
    """Détail d'une conversation de chat."""
    user = request.user
    other_user = get_object_or_404(User, id=user_id)
    
    # Vérifier si l'utilisateur a Mobility Plus
    user_has_plus = user_has_mobility_plus(user)
    
    # Récupérer les messages
    messages = ChatMessage.objects.filter(
        Q(sender=user, recipient=other_user) | 
        Q(sender=other_user, recipient=user)
    ).order_by('created_at')
    
    # Marquer les messages reçus comme lus
    ChatMessage.objects.filter(sender=other_user, recipient=user, is_read=False).update(is_read=True)
    
    context = {
        'other_user': other_user,
        'messages': messages,
        'user_has_mobility_plus': user_has_plus,
        'other_user_has_mobility_plus': user_has_mobility_plus(other_user)
    }
    
    return render(request, 'subscriptions/chat_detail.html', context)


@login_required
def send_message(request):
    """Envoyer un message de chat."""
    if request.method == 'POST':
        try:
            recipient_id = request.POST.get('recipient_id')
            message_text = request.POST.get('message', '').strip()
            
            if not recipient_id or not message_text:
                return JsonResponse({
                    'success': False,
                    'error': 'Destinataire et message requis'
                })
            
            recipient = get_object_or_404(User, id=recipient_id)
            
            # Vérifier si l'utilisateur a Mobility Plus
            if not user_has_mobility_plus(request.user):
                return JsonResponse({
                    'success': False,
                    'error': 'Vous devez avoir un abonnement Mobility Plus pour envoyer des messages'
                })
            
            # Créer le message
            message = ChatMessage.objects.create(
                sender=request.user,
                recipient=recipient,
                message=message_text
            )
            
            return JsonResponse({
                'success': True,
                'message': {
                    'id': message.id,
                    'text': message.message,
                    'sender': message.sender.get_full_name(),
                    'created_at': message.created_at.strftime('%H:%M'),
                    'sender_has_mobility_plus': message.sender_has_mobility_plus
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


def user_has_mobility_plus(user):
    """Vérifier si un utilisateur a un abonnement Mobility Plus actif."""
    try:
        mobility_plus = user.mobility_plus_subscription
        return mobility_plus.is_active and mobility_plus.status == 'active'
    except:
        return False


@login_required
def delete_chauffeur_request(request, request_id):
    """Permettre au parent de supprimer une demande refusée ou annulée."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})

    subscription_request = get_object_or_404(
        ChauffeurSubscriptionRequest,
        id=request_id,
        parent=request.user,
    )

    if subscription_request.status not in {'rejected', 'cancelled'}:
        return JsonResponse({'success': False, 'error': 'Cette demande ne peut pas être supprimée'})

    subscription_request.delete()
    return JsonResponse({'success': True})
