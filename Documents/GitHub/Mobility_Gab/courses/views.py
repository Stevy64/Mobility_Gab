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
from .models import TripMessage, TripUpdate


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
        
        # Récupérer les messages du chat
        if context['has_mobility_plus']:
            context['messages'] = TripMessage.objects.filter(trip=trip)
        
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
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    trip = get_object_or_404(Trip, pk=trip_id)
    
    # Vérifier l'accès
    if request.user != trip.chauffeur and request.user != trip.parent:
        return JsonResponse({'error': 'Accès non autorisé'}, status=403)
    
    # TODO: Vérifier l'abonnement Mobility Plus
    # Pour le MVP, on autorise tout le monde
    
    message_text = request.POST.get('message', '').strip()
    if not message_text:
        return JsonResponse({'error': 'Message vide'}, status=400)
    
    # Créer le message
    message = TripMessage.objects.create(
        trip=trip,
        sender=request.user,
        message=message_text
    )
    
    # Note: Les notifications de chat sont gérées via le polling JavaScript
    # Pas besoin de créer des notifications persistantes pour les messages
    
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
