"""
Vues pour la gestion des courses en temps réel.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView, DetailView, ListView
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q

from subscriptions.models import Trip, RideRequest
from accounts.models import UserRoles
from core.models import NotificationLog
from core.notifications import notification_service
from .models import TripMessage, TripUpdate, TripRating


def _trip_status_payload(trip: Trip) -> dict:
    return {
        "id": trip.id,
        "status": trip.status,
        "status_display": trip.get_status_display(),
        "started_at": trip.started_at.isoformat() if trip.started_at else None,
        "completed_at": trip.completed_at.isoformat() if trip.completed_at else None,
        "chauffeur_confirmed": trip.chauffeur_has_confirmed,
        "parent_confirmed": trip.parent_has_confirmed,
        "awaiting_parent_confirmation": trip.awaiting_parent_confirmation,
        "awaiting_chauffeur_confirmation": trip.awaiting_chauffeur_confirmation,
    }


def _notify_trip_user(trip: Trip, user, title: str, message: str, notification_type: str = "trip_update") -> None:
    NotificationLog.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
    )
    try:
        notification_service.send_notification(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            channels=["in_app", "push"],
        )
    except Exception:  # pragma: no cover - notifications shouldn't break flow
        pass


def _finalize_trip_completion(trip: Trip) -> bool:
    if trip.chauffeur_has_confirmed and trip.parent_has_confirmed and trip.status != "completed":
        trip.mark_completed()
        TripUpdate.objects.create(
            trip=trip,
            update_type="completed",
            message="Course confirmée par les deux parties.",
        )
        completion_title = "Course clôturée"
        completion_message = "La course est terminée et confirmée par les deux parties. Merci pour votre confiance !"
        _notify_trip_user(trip, trip.parent, completion_title, completion_message, "trip_confirmation")
        _notify_trip_user(trip, trip.chauffeur, completion_title, completion_message, "trip_confirmation")
        return True
    return False


class TripManagementView(LoginRequiredMixin, DetailView):
    """
    Vue principale de gestion de course pour chauffeur et particulier.
    """
    model = Trip
    template_name = 'courses/trip_management.html'
    context_object_name = 'trip'
    
    def dispatch(self, request, *args, **kwargs):
        """Vérifier que l'utilisateur a accès à cette course."""
        trip = get_object_or_404(Trip, pk=kwargs['pk'])
        
        # Seuls le chauffeur et le particulier de la course peuvent y accéder
        if request.user != trip.chauffeur and request.user != trip.parent:
            messages.error(request, "Vous n'avez pas accès à cette course.")
            return redirect('core:dashboard')
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        """Ajouter les données contextuelles."""
        context = super().get_context_data(**kwargs)
        trip = self.get_object()
        
        # Déterminer le rôle de l'utilisateur
        context['is_chauffeur'] = self.request.user == trip.chauffeur
        context['is_parent'] = self.request.user == trip.parent
        context['chauffeur_confirmed'] = trip.chauffeur_has_confirmed
        context['parent_confirmed'] = trip.parent_has_confirmed
        context['awaiting_parent_confirmation'] = trip.awaiting_parent_confirmation
        context['awaiting_chauffeur_confirmation'] = trip.awaiting_chauffeur_confirmation
        
        # Vérifier si l'utilisateur a Mobility Plus pour le chat
        try:
            mobility_plus = self.request.user.mobility_plus_subscription
            context['has_mobility_plus'] = mobility_plus.is_active and mobility_plus.status == 'active'
        except:
            context['has_mobility_plus'] = False
        
        # Vérifier si l'AUTRE utilisateur a Mobility Plus
        other_user = trip.chauffeur if self.request.user == trip.parent else trip.parent
        try:
            other_mobility_plus = other_user.mobility_plus_subscription
            context['other_has_mobility_plus'] = other_mobility_plus.is_active and other_mobility_plus.status == 'active'
        except:
            context['other_has_mobility_plus'] = False
        
        # Récupérer les messages du chat
        # Les non-abonnés peuvent VOIR les messages reçus mais pas répondre
        if context['has_mobility_plus'] or context['other_has_mobility_plus']:
            context['messages'] = TripMessage.objects.filter(trip=trip)
            # Compter les messages non lus reçus
            context['unread_messages_count'] = TripMessage.objects.filter(
                trip=trip, 
                is_read=False
            ).exclude(sender=self.request.user).count()
        
        # Récupérer les mises à jour de la course
        context['updates'] = TripUpdate.objects.filter(trip=trip)[:10]
        
        # Informations sur l'autre participant (sans infos confidentielles)
        if context['is_chauffeur']:
            context['other_user'] = {
                'name': trip.parent.get_full_name() or trip.parent.username,
                'role': 'Particulier',
                'avatar': getattr(trip.parent.profile, 'photo', None) if hasattr(trip.parent, 'profile') else None
            }
        else:
            chauffeur_profile = trip.chauffeur.chauffeur_profile
            context['other_user'] = {
                'name': trip.chauffeur.get_full_name() or trip.chauffeur.username,
                'role': 'Chauffeur',
                'avatar': getattr(trip.chauffeur.profile, 'photo', None) if hasattr(trip.chauffeur, 'profile') else None,
                'vehicle': f"{chauffeur_profile.vehicle_make} {chauffeur_profile.vehicle_model}".strip() or "Véhicule non renseigné",
                'plate': chauffeur_profile.vehicle_plate or "Non renseignée",
                'rating': chauffeur_profile.reliability_score
            }
        
        # Informations de la course
        ride_request = getattr(trip, 'riderequest_set', RideRequest.objects.filter(trip=trip)).first()
        if ride_request:
            context['pickup_location'] = ride_request.pickup_location
            context['dropoff_location'] = ride_request.dropoff_location
            context['pickup_time'] = ride_request.requested_pickup_time
        
        return context


class CoursesMenuView(LoginRequiredMixin, TemplateView):
    """
    Vue du menu principal de gestion des courses avec les 3 boutons.
    """
    template_name = 'courses/courses_menu.html'
    
    def get_context_data(self, **kwargs):
        """Ajouter les statistiques pour les boutons."""
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Statistiques pour les boutons
        if user.role == UserRoles.CHAUFFEUR:
            # Courses actives
            active_trips = Trip.objects.filter(
                chauffeur=user,
                status__in=['in_progress', 'scheduled']
            ).count()
            
            # Demandes en attente
            pending_requests = RideRequest.objects.filter(
                status='pending'
            ).count()
            
            # Historique
            completed_trips = Trip.objects.filter(
                chauffeur=user,
                status='completed'
            ).count()
            
        else:  # Particulier
            # Courses actives
            active_trips = Trip.objects.filter(
                parent=user,
                status__in=['in_progress', 'scheduled']
            ).count()
            
            # Demandes en attente
            pending_requests = RideRequest.objects.filter(
                parent=user,
                status='pending'
            ).count()
            
            # Historique
            completed_trips = Trip.objects.filter(
                parent=user,
                status='completed'
            ).count()
        
        context.update({
            'active_trips_count': active_trips,
            'pending_requests_count': pending_requests,
            'completed_trips_count': completed_trips,
            'is_chauffeur': user.role == UserRoles.CHAUFFEUR,
            'is_parent': user.role == UserRoles.PARENT
        })
        
        return context


class ActiveTripsView(LoginRequiredMixin, TemplateView):
    """
    Vue magnifique pour afficher toutes les courses en cours de l'utilisateur.
    """
    template_name = 'courses/active_trips.html'
    
    def get_context_data(self, **kwargs):
        """Ajouter les courses actives de l'utilisateur."""
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Récupérer les courses actives selon le rôle (exclure les archivées)
        if user.role == UserRoles.CHAUFFEUR:
            active_trips = Trip.objects.filter(
                chauffeur=user,
                status__in=['in_progress', 'scheduled']
            ).select_related('parent', 'chauffeur')
        else:  # Particulier
            active_trips = Trip.objects.filter(
                parent=user,
                status__in=['in_progress', 'scheduled']
            ).select_related('parent', 'chauffeur')
        
        context.update({
            'active_trips': active_trips.order_by('-scheduled_date'),
            'is_chauffeur': user.role == UserRoles.CHAUFFEUR,
            'is_parent': user.role == UserRoles.PARENT
        })
        
        return context


class TripListView(LoginRequiredMixin, ListView):
    """Liste paginée des courses pour le parent ou le chauffeur (hors archivées personnelles)."""

    template_name = 'courses/trip_list.html'
    context_object_name = 'trips'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        queryset = Trip.objects.select_related('parent', 'chauffeur').order_by('-scheduled_date', '-started_at')
        status = self.request.GET.get('status')
        role_filter = self.request.GET.get('role')

        if user.role == UserRoles.CHAUFFEUR:
            queryset = queryset.filter(chauffeur=user, chauffeur_archived=False)
        elif user.role == UserRoles.PARENT:
            queryset = queryset.filter(parent=user, parent_archived=False)
        else:
            # Admin peut tout voir mais peut filtrer par rôle
            if role_filter == 'chauffeur':
                queryset = queryset.filter(chauffeur__isnull=False)
            elif role_filter == 'parent':
                queryset = queryset.filter(parent__isnull=False)

        if status:
            statuses = [s.strip() for s in status.split(',') if s.strip()]
            queryset = queryset.filter(status__in=statuses)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        context.update({
            'is_chauffeur': user.role == UserRoles.CHAUFFEUR,
            'is_parent': user.role == UserRoles.PARENT,
            'active_count': Trip.objects.filter(status__in=['in_progress', 'scheduled'], **self._role_filter(user)).count(),
            'completed_count': Trip.objects.filter(status='completed', **self._role_filter(user)).count(),
            'cancelled_count': Trip.objects.filter(status='cancelled', **self._role_filter(user)).count(),
            'archived_count': Trip.objects.filter(status='archived', **self._role_filter(user)).count(),
        })
        return context

    def _role_filter(self, user):
        if user.role == UserRoles.CHAUFFEUR:
            return {'chauffeur': user, 'chauffeur_archived': False}
        if user.role == UserRoles.PARENT:
            return {'parent': user, 'parent_archived': False}
        return {}


@login_required
def send_message(request, trip_id):
    """
    API pour envoyer un message dans le chat de la course.
    Seuls les abonnés Mobility+ peuvent envoyer des messages.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    trip = get_object_or_404(Trip, pk=trip_id)
    
    # Vérifier l'accès
    if request.user != trip.chauffeur and request.user != trip.parent:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    # Vérifier l'abonnement Mobility Plus de l'expéditeur
    try:
        mobility_plus = request.user.mobility_plus_subscription
        if not (mobility_plus.is_active and mobility_plus.status == 'active'):
            return JsonResponse({'error': 'Abonnement Mobility Plus requis pour envoyer des messages'}, status=403)
    except:
        return JsonResponse({'error': 'Abonnement Mobility Plus requis pour envoyer des messages'}, status=403)
    
    message_text = request.POST.get('message', '').strip()
    if not message_text:
        return JsonResponse({'error': 'Message vide'}, status=400)
    
    # Créer le message
    message = TripMessage.objects.create(
        trip=trip,
        sender=request.user,
        message=message_text
    )
    
    # Créer une notification UNIQUEMENT pour le destinataire
    recipient = trip.parent if request.user == trip.chauffeur else trip.chauffeur
    NotificationLog.objects.create(
        user=recipient,
        title=f"💬 Nouveau message de {request.user.get_full_name() or request.user.username}",
        message=message_text[:100] + ('...' if len(message_text) > 100 else ''),
        notification_type="chat_message",
        metadata={
            'trip_id': trip.id,
            'message_id': message.id,
            'sender_id': request.user.id
        }
    )
    
    return JsonResponse({
        'success': True,
        'message': {
            'id': message.id,
            'sender': request.user.get_full_name() or request.user.username,
            'message': message.message,
            'timestamp': message.timestamp.strftime('%H:%M'),
            'is_own': True
        }
    })


@login_required
def get_messages(request, trip_id):
    """
    API pour récupérer les messages du chat.
    Marque automatiquement les notifications de chat comme lues (affichage unique).
    """
    trip = get_object_or_404(Trip, pk=trip_id)
    
    # Vérifier l'accès
    if request.user != trip.chauffeur and request.user != trip.parent:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    messages = TripMessage.objects.filter(trip=trip).order_by('timestamp')
    
    messages_data = []
    for msg in messages:
        messages_data.append({
            'id': msg.id,
            'sender': msg.sender.get_full_name() or msg.sender.username,
            'message': msg.message,
            'timestamp': msg.timestamp.strftime('%H:%M'),
            'is_own': msg.sender == request.user
        })
    
    # Marquer les notifications de chat comme lues pour cet utilisateur (affichage unique)
    # Les notifications disparaissent après consultation
    import json
    chat_notifications = NotificationLog.objects.filter(
        user=request.user,
        notification_type="chat_message",
        is_read=False
    )
    
    # Filtrer les notifications liées à ce trajet
    for notif in chat_notifications:
        try:
            metadata = json.loads(notif.metadata) if isinstance(notif.metadata, str) else notif.metadata
            if metadata and metadata.get('trip_id') == trip.id:
                notif.is_read = True
                notif.save(update_fields=['is_read'])
        except:
            pass
    
    return JsonResponse({
        'messages': messages_data,
        'timestamp': timezone.now().isoformat()
    })


@login_required
def update_trip_status(request, trip_id):
    """
    API pour mettre à jour le statut de la course.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    trip = get_object_or_404(Trip, pk=trip_id)
    
    # Seul le chauffeur peut mettre à jour le statut
    if request.user != trip.chauffeur:
        return JsonResponse({'error': 'Seul le chauffeur peut mettre à jour le statut'}, status=403)
    
    update_type = request.POST.get('update_type')
    message = request.POST.get('message', '')
    latitude = request.POST.get('latitude')
    longitude = request.POST.get('longitude')
    
    if not update_type:
        return JsonResponse({'error': 'Type de mise à jour requis'}, status=400)
    
    # Créer la mise à jour
    update = TripUpdate.objects.create(
        trip=trip,
        update_type=update_type,
        message=message,
        latitude=latitude if latitude else None,
        longitude=longitude if longitude else None
    )
    
    # Mettre à jour le statut du trip si nécessaire
    if update_type == 'started':
        trip.mark_in_progress()
    elif update_type == 'completed':
        trip.mark_completed()
    
    # Notifier le particulier
    notification_service.send_notification(
        user=trip.parent,
        title=f"🚗 {update.get_update_type_display()}",
        message=message or f"Votre chauffeur a mis à jour le statut de la course: {update.get_update_type_display()}",
        notification_type="trip_update",
        channels=['in_app', 'push']
    )
    
    return JsonResponse({
        'success': True,
        'update': {
            'type': update.get_update_type_display(),
            'message': update.message,
            'timestamp': update.timestamp.strftime('%H:%M')
        }
    })


@login_required
def mark_notifications_read(request):
    """
    API pour supprimer définitivement les notifications.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    notification_ids = request.POST.getlist('notification_ids[]')
    
    if notification_ids:
        # Supprimer les notifications spécifiques
        count = NotificationLog.objects.filter(
            id__in=notification_ids,
            user=request.user
        ).delete()[0]
    else:
        # Supprimer toutes les notifications non lues
        count = NotificationLog.objects.filter(
            user=request.user,
            read=False
        ).delete()[0]
    
    return JsonResponse({
        'success': True,
        'deleted_count': count
    })


@login_required
def mark_messages_read(request, trip_id):
    """
    API pour marquer les messages d'une course comme lus.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    trip = get_object_or_404(Trip, pk=trip_id)
    
    # Vérifier l'accès
    if request.user != trip.chauffeur and request.user != trip.parent:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    # Marquer tous les messages non lus comme lus par cet utilisateur
    unread_messages = TripMessage.objects.filter(
        trip=trip,
        is_read=False
    ).exclude(sender=request.user)  # Exclure les messages envoyés par l'utilisateur
    
    for message in unread_messages:
        message.mark_as_read_by(request.user)
    
    return JsonResponse({'success': True, 'marked_count': unread_messages.count()})


@login_required
def archive_trip(request, trip_id):
    """
    API pour archiver une course terminée.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    trip = get_object_or_404(Trip, pk=trip_id)
    
    # Vérifier l'accès
    if request.user != trip.chauffeur and request.user != trip.parent:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    # Archiver pour l'utilisateur courant (per-user archive)
    if trip.archive(request.user):
        return JsonResponse({'success': True, 'message': 'Course archivée'})
    return JsonResponse({'error': "Impossible d'archiver cette course"}, status=400)


@login_required
def start_trip(request, trip_id):
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)

    trip = get_object_or_404(Trip, pk=trip_id)

    if request.user != trip.chauffeur:
        return JsonResponse({"error": "Seul le chauffeur peut démarrer la course"}, status=403)
    if trip.status not in {"scheduled", "in_progress"}:
        return JsonResponse({"error": "Cette course ne peut pas être démarrée"}, status=400)

    trip.mark_in_progress()
    TripUpdate.objects.create(
        trip=trip,
        update_type="started",
        message="Course démarrée par le chauffeur.",
    )
    _notify_trip_user(
        trip,
        trip.parent,
        "Course démarrée",
        f"{trip.chauffeur.get_full_name() or trip.chauffeur.username} a démarré la course.",
    )

    return JsonResponse({"success": True, "trip": _trip_status_payload(trip)})


@login_required
def confirm_trip_completion(request, trip_id):
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)

    trip = get_object_or_404(Trip, pk=trip_id)

    if request.user not in {trip.chauffeur, trip.parent}:
        return JsonResponse({"error": "Accès non autorisé"}, status=403)

    if trip.status != "in_progress":
        return JsonResponse({"error": "La course doit être en cours pour être confirmée"}, status=400)

    now = timezone.now()
    actor_role = "chauffeur" if request.user == trip.chauffeur else "parent"

    if actor_role == "chauffeur":
        if trip.chauffeur_has_confirmed:
            return JsonResponse({"error": "Vous avez déjà confirmé la fin"}, status=400)
        trip.chauffeur_confirmed_completion_at = now
    else:
        if trip.parent_has_confirmed:
            return JsonResponse({"error": "Vous avez déjà confirmé la fin"}, status=400)
        trip.parent_confirmed_completion_at = now

    trip.save(
        update_fields=[
            "chauffeur_confirmed_completion_at",
            "parent_confirmed_completion_at",
        ]
    )

    just_completed = _finalize_trip_completion(trip)

    TripUpdate.objects.create(
        trip=trip,
        update_type="completed" if just_completed else "destination_reached",
        message=(
            "Confirmation de fin de course par le chauffeur."
            if actor_role == "chauffeur"
            else "Confirmation de fin de course par le particulier."
        ),
    )

    counterpart = trip.parent if actor_role == "chauffeur" else trip.chauffeur
    _notify_trip_user(
        trip,
        counterpart,
        "Confirmation reçue",
        f"{request.user.get_full_name() or request.user.username} a confirmé la fin de la course.",
        "trip_confirmation",
    )

    return JsonResponse({"success": True, "trip": _trip_status_payload(trip)})


@login_required
def delete_trip(request, trip_id):
    """Permettre à l'utilisateur de supprimer localement une course annulée."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)

    trip = get_object_or_404(Trip, pk=trip_id)

    if request.user not in {trip.parent, trip.chauffeur}:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)

    if trip.status not in {'cancelled', 'completed', 'archived'}:
        return JsonResponse({'error': 'Seules les courses annulées ou terminées peuvent être supprimées'}, status=400)

    trip.archive(request.user)
    return JsonResponse({'success': True})


@login_required
def get_trip_gps_location(request, trip_id):
    """
    API pour récupérer la position GPS en temps réel du chauffeur et l'historique des checkpoints.
    Accessible uniquement au chauffeur et au particulier de la course.
    """
    trip = get_object_or_404(Trip, pk=trip_id)
    
    # Vérifier l'autorisation
    if request.user not in {trip.parent, trip.chauffeur}:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    # Récupérer le profil chauffeur
    chauffeur_profile = trip.chauffeur.chauffeur_profile
    
    # Position actuelle du chauffeur
    current_location = {
        'latitude': float(chauffeur_profile.current_latitude) if chauffeur_profile.current_latitude else None,
        'longitude': float(chauffeur_profile.current_longitude) if chauffeur_profile.current_longitude else None,
        'last_update': chauffeur_profile.last_location_update.isoformat() if chauffeur_profile.last_location_update else None,
    }
    
    # Récupérer tous les checkpoints de la course
    checkpoints = trip.checkpoints.all().order_by('timestamp')
    checkpoints_data = [{
        'id': cp.id,
        'type': cp.checkpoint_type,
        'type_display': cp.get_checkpoint_type_display(),
        'latitude': float(cp.latitude),
        'longitude': float(cp.longitude),
        'timestamp': cp.timestamp.isoformat(),
        'notes': cp.notes,
    } for cp in checkpoints]
    
    # Récupérer les informations de la demande de course (départ et destination)
    ride_request = RideRequest.objects.filter(trip=trip).first()
    route_info = {}
    if ride_request:
        route_info = {
            'pickup': {
                'location': ride_request.pickup_location,
                'latitude': float(ride_request.pickup_latitude) if ride_request.pickup_latitude else None,
                'longitude': float(ride_request.pickup_longitude) if ride_request.pickup_longitude else None,
            },
            'dropoff': {
                'location': ride_request.dropoff_location,
                'latitude': float(ride_request.dropoff_latitude) if ride_request.dropoff_latitude else None,
                'longitude': float(ride_request.dropoff_longitude) if ride_request.dropoff_longitude else None,
            }
        }
    
    # Statut de la course
    trip_status = {
        'status': trip.status,
        'status_display': trip.get_status_display(),
        'started_at': trip.started_at.isoformat() if trip.started_at else None,
        'completed_at': trip.completed_at.isoformat() if trip.completed_at else None,
        'distance_km': float(trip.distance_km) if trip.distance_km else None,
        'duration_minutes': trip.duration_minutes,
        'chauffeur_confirmed': trip.chauffeur_has_confirmed,
        'parent_confirmed': trip.parent_has_confirmed,
    }
    
    # Données exploitables supplémentaires pour Mobility+ uniquement
    mobility_plus_data = None
    if request.user == trip.parent or request.user == trip.chauffeur:
        try:
            user_mobility_plus = request.user.mobility_plus_subscription
            if user_mobility_plus.is_active and user_mobility_plus.status == 'active':
                # Calculer des statistiques avancées
                from django.db.models import Avg, Count
                from datetime import timedelta
                
                # Vitesse moyenne estimée
                avg_speed = None
                if trip.distance_km and trip.duration_minutes:
                    avg_speed = round((float(trip.distance_km) / (trip.duration_minutes / 60)), 2)
                
                # Temps estimé d'arrivée
                eta = None
                if trip.status == 'in_progress' and ride_request and ride_request.dropoff_latitude and ride_request.dropoff_longitude:
                    if current_location['latitude'] and current_location['longitude']:
                        # Calculer la distance restante approximative
                        from math import radians, sin, cos, sqrt, atan2
                        
                        lat1, lon1 = radians(current_location['latitude']), radians(current_location['longitude'])
                        lat2, lon2 = radians(float(ride_request.dropoff_latitude)), radians(float(ride_request.dropoff_longitude))
                        
                        dlat = lat2 - lat1
                        dlon = lon2 - lon1
                        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                        c = 2 * atan2(sqrt(a), sqrt(1-a))
                        distance_remaining = 6371 * c  # Rayon de la Terre en km
                        
                        if avg_speed and avg_speed > 0:
                            eta_minutes = round((distance_remaining / avg_speed) * 60, 1)
                            eta = {
                                'distance_remaining_km': round(distance_remaining, 2),
                                'minutes_remaining': eta_minutes
                            }
                
                # Historique de vitesse (basé sur les checkpoints)
                speed_history = []
                if len(checkpoints) > 1:
                    for i in range(1, min(len(checkpoints), 6)):  # Les 5 derniers segments
                        prev_cp = checkpoints[i-1]
                        curr_cp = checkpoints[i]
                        
                        # Calculer distance entre 2 checkpoints
                        from math import radians, sin, cos, sqrt, atan2
                        lat1, lon1 = radians(prev_cp.latitude), radians(prev_cp.longitude)
                        lat2, lon2 = radians(curr_cp.latitude), radians(curr_cp.longitude)
                        
                        dlat = lat2 - lat1
                        dlon = lon2 - lon1
                        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                        c = 2 * atan2(sqrt(a), sqrt(1-a))
                        segment_distance = 6371 * c
                        
                        # Calculer temps entre 2 checkpoints
                        time_diff = (curr_cp.timestamp - prev_cp.timestamp).total_seconds() / 3600
                        
                        if time_diff > 0:
                            segment_speed = round(segment_distance / time_diff, 1)
                            speed_history.append({
                                'speed_kmh': segment_speed,
                                'timestamp': curr_cp.timestamp.isoformat()
                            })
                
                mobility_plus_data = {
                    'avg_speed_kmh': avg_speed,
                    'eta': eta,
                    'speed_history': speed_history,
                    'total_checkpoints': len(checkpoints),
                    'gps_accuracy': 'high' if len(checkpoints) > 10 else 'medium'
                }
        except:
            pass
    
    response_data = {
        'success': True,
        'current_location': current_location,
        'checkpoints': checkpoints_data,
        'route_info': route_info,
        'trip_status': trip_status,
    }
    
    if mobility_plus_data:
        response_data['mobility_plus_data'] = mobility_plus_data
    
    return JsonResponse(response_data)


class TripRatingView(LoginRequiredMixin, DetailView):
    """
    Vue pour évaluer un trajet terminé (modèle Heetch).
    """
    model = Trip
    template_name = 'courses/trip_rating.html'
    context_object_name = 'trip'
    
    def dispatch(self, request, *args, **kwargs):
        """Vérifier que l'utilisateur a accès à cette course et qu'elle est terminée."""
        trip = get_object_or_404(Trip, pk=kwargs['pk'])
        
        # Seuls le chauffeur et le particulier de la course peuvent y accéder
        if request.user not in {trip.parent, trip.chauffeur}:
            messages.error(request, "Vous n'avez pas accès à cette course.")
            return redirect('core:dashboard')
        
        # La course doit être terminée
        if trip.status != 'completed':
            messages.warning(request, "Cette course n'est pas encore terminée.")
            return redirect('courses:chauffeur_management' if request.user == trip.chauffeur else 'courses:particulier_management', pk=trip.id)
        
        # Vérifier si l'utilisateur a déjà évalué
        other_user = trip.chauffeur if request.user == trip.parent else trip.parent
        existing_rating = TripRating.objects.filter(trip=trip, rater=request.user, rated=other_user).first()
        if existing_rating:
            messages.info(request, "Vous avez déjà évalué cette course.")
            return redirect('courses:active_trips')
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        """Ajouter les données contextuelles."""
        context = super().get_context_data(**kwargs)
        trip = self.get_object()
        
        # Déterminer le rôle de l'utilisateur et l'autre partie
        context['is_chauffeur'] = self.request.user == trip.chauffeur
        context['other_user'] = trip.chauffeur if self.request.user == trip.parent else trip.parent
        
        # Informations de base sur l'autre utilisateur
        other_user = context['other_user']
        context['other_user_info'] = {
            'name': other_user.get_full_name() or other_user.username,
            'role': 'Chauffeur' if context['is_chauffeur'] else 'Particulier',
            'avatar': getattr(other_user.profile, 'photo', None) if hasattr(other_user, 'profile') else None
        }
        
        return context
    
    def post(self, request, *args, **kwargs):
        """Enregistrer l'évaluation."""
        trip = self.get_object()
        other_user = trip.chauffeur if request.user == trip.parent else trip.parent
        
        # Récupérer les données du formulaire
        stars = request.POST.get('stars')
        was_on_time = request.POST.get('was_on_time') == 'true'
        was_polite = request.POST.get('was_polite') == 'true'
        was_safe = request.POST.get('was_safe') == 'true' if request.POST.get('was_safe') else None
        vehicle_clean = request.POST.get('vehicle_clean') == 'true' if request.POST.get('vehicle_clean') else None
        comment = request.POST.get('comment', '').strip()
        
        # Validation
        if not stars or not stars.isdigit() or int(stars) not in range(1, 6):
            messages.error(request, "Veuillez donner une note de 1 à 5 étoiles.")
            return redirect('courses:rate_trip', pk=trip.id)
        
        # Créer l'évaluation
        rating = TripRating.objects.create(
            trip=trip,
            rater=request.user,
            rated=other_user,
            stars=int(stars),
            was_on_time=was_on_time,
            was_polite=was_polite,
            was_safe=was_safe,
            vehicle_clean=vehicle_clean,
            comment=comment[:500]  # Limiter à 500 caractères
        )
        
        # Mettre à jour la note moyenne du chauffeur ou particulier évalué
        _update_user_rating(other_user)
        
        # Notifier l'autre utilisateur
        NotificationLog.objects.create(
            user=other_user,
            title="Nouvelle évaluation",
            message=f"{request.user.get_full_name() or request.user.username} vous a donné {stars} étoile{'s' if int(stars) > 1 else ''}.",
            notification_type="rating_received"
        )
        
        messages.success(request, "Merci pour votre évaluation !")
        return redirect('courses:active_trips')


def _update_user_rating(user):
    """
    Mettre à jour la note moyenne d'un utilisateur en fonction de ses évaluations reçues.
    """
    from django.db.models import Avg
    
    # Calculer la moyenne des notes reçues
    avg_rating = TripRating.objects.filter(rated=user).aggregate(avg=Avg('stars'))['avg']
    
    # Mettre à jour le profil approprié
    if user.role == 'chauffeur' and hasattr(user, 'chauffeur_profile'):
        user.chauffeur_profile.reliability_score = round(avg_rating, 2) if avg_rating else 0
        user.chauffeur_profile.save(update_fields=['reliability_score'])
    elif user.role == 'parent' and hasattr(user, 'profile'):
        # Ajouter un champ rating dans le profil parent si nécessaire
        pass
