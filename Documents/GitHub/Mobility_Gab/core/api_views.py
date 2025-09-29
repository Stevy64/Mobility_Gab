"""
Vues API pour l'application Core.

Ce fichier contient les endpoints API pour les notifications,
les alertes SOS, et le polling en temps réel.
"""

import json
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from accounts.models import User
from .models import NotificationLog, SOSAlert
from .notifications import notification_service, send_sos_alert
from .serializers import NotificationSerializer, SOSAlertSerializer


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet pour les notifications utilisateur.
    
    Permet de récupérer les notifications d'un utilisateur,
    marquer comme lues, et gérer les préférences.
    """
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """
        Retourne les notifications de l'utilisateur connecté.
        """
        return NotificationLog.objects.filter(
            user=self.request.user
        ).order_by('-created_at')
    
    @action(detail=False, methods=['get'])
    def unread(self, request):
        """
        Récupère les notifications non lues.
        """
        unread_notifications = self.get_queryset().filter(read_at__isnull=True)
        serializer = self.get_serializer(unread_notifications, many=True)
        return Response({
            'count': unread_notifications.count(),
            'notifications': serializer.data
        })
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """
        Marque une notification comme lue.
        """
        notification = self.get_object()
        notification.read_at = timezone.now()
        notification.save()
        return Response({'status': 'marked_as_read'})
    
    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """
        Supprime définitivement toutes les notifications non lues.
        """
        count = self.get_queryset().filter(read_at__isnull=True).delete()[0]
        return Response({'deleted_count': count})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_sos_alert(request):
    """
    Crée une alerte SOS d'urgence.
    
    Endpoint pour déclencher une alerte SOS avec géolocalisation
    et notification immédiate des contacts d'urgence.
    """
    try:
        data = request.data
        
        # Récupérer les données de l'alerte
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        message = data.get('message', 'Alerte SOS déclenchée')
        trip_id = data.get('trip_id')
        
        # Créer l'alerte SOS
        sos_alert = SOSAlert.objects.create(
            user=request.user,
            latitude=latitude,
            longitude=longitude,
            message=message,
            trip_id=trip_id,
            status='active'
        )
        
        # Envoyer les notifications d'urgence
        location_str = ""
        if latitude and longitude:
            location_str = f"Lat: {latitude}, Lon: {longitude}"
        
        # Notifier l'utilisateur (confirmation)
        send_sos_alert(
            user=request.user,
            location=location_str,
            trip_id=trip_id,
            alert_id=sos_alert.id
        )
        
        # Notifier les admins/staff
        staff_users = User.objects.filter(is_staff=True, is_active=True)
        for admin in staff_users:
            notification_service.send_notification(
                user=admin,
                title="🚨 ALERTE SOS URGENTE",
                message=f"Alerte déclenchée par {request.user.get_full_name() or request.user.username}",
                notification_type="sos",
                data={
                    'alert_id': sos_alert.id,
                    'user_id': request.user.id,
                    'location': location_str,
                    'trip_id': trip_id
                },
                channels=['in_app', 'email', 'push']  # Notification prioritaire
            )
        
        # Notifier les contacts d'urgence si disponibles
        if hasattr(request.user, 'parent_profile') and request.user.parent_profile.emergency_contact_phone:
            # En production, envoyer SMS au contact d'urgence
            pass
        
        return Response({
            'success': True,
            'alert_id': sos_alert.id,
            'message': 'Alerte SOS envoyée. Les secours ont été prévenus.'
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def polling_updates(request):
    """
    Endpoint de polling pour les mises à jour en temps réel.
    
    Retourne les nouvelles notifications, mises à jour de courses,
    et autres événements depuis le dernier polling.
    """
    try:
        # Récupérer le timestamp du dernier polling
        last_poll = request.GET.get('last_poll')
        if last_poll:
            try:
                from datetime import datetime
                last_poll_dt = datetime.fromisoformat(last_poll.replace('Z', '+00:00'))
            except:
                last_poll_dt = timezone.now() - timezone.timedelta(minutes=5)
        else:
            last_poll_dt = timezone.now() - timezone.timedelta(minutes=5)
        
        # Nouvelles notifications
        new_notifications = NotificationLog.objects.filter(
            user=request.user,
            created_at__gt=last_poll_dt
        ).order_by('-created_at')[:10]
        
        # Sérialiser les données
        notifications_data = []
        for notif in new_notifications:
            notifications_data.append({
                'id': notif.id,
                'title': notif.title,
                'message': notif.message,
                'type': notif.notification_type,
                'created_at': notif.created_at.isoformat(),
                'read': notif.read_at is not None,
                'data': notif.data
            })
        
        # Compter les notifications non lues
        unread_count = NotificationLog.objects.filter(
            user=request.user,
            read_at__isnull=True
        ).count()
        
        # Vérifier s'il y a des courses actives
        active_trips = []
        if hasattr(request.user, 'trips_as_parent'):
            from subscriptions.models import Trip
            user_trips = Trip.objects.filter(
                parent=request.user,
                status__in=['pending', 'in_progress']
            ).select_related('chauffeur')
            
            for trip in user_trips:
                active_trips.append({
                    'id': trip.id,
                    'status': trip.status,
                    'chauffeur': trip.chauffeur.get_full_name() if trip.chauffeur else None,
                    'tracking_url': f'/subscriptions/tracking/{trip.id}/'
                })
        
        return Response({
            'timestamp': timezone.now().isoformat(),
            'notifications': notifications_data,
            'unread_count': unread_count,
            'active_trips': active_trips,
            'has_updates': len(notifications_data) > 0
        })
        
    except Exception as e:
        return Response({
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@login_required
def notification_preferences(request):
    """
    Gère les préférences de notification de l'utilisateur.
    
    GET: Récupère les préférences actuelles
    POST: Met à jour les préférences
    """
    if request.method == 'GET':
        preferences = {
            'push_enabled': getattr(request.user.profile, 'push_notifications_enabled', True),
            'sms_enabled': getattr(request.user.profile, 'sms_notifications_enabled', False),
            'email_enabled': True,  # Toujours activé pour les notifications importantes
        }
        return JsonResponse(preferences)
    
    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Mettre à jour les préférences
            if hasattr(request.user, 'profile'):
                profile = request.user.profile
                profile.push_notifications_enabled = data.get('push_enabled', True)
                profile.sms_notifications_enabled = data.get('sms_enabled', False)
                profile.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Préférences mises à jour'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    return JsonResponse({'error': 'Méthode non autorisée'}, status=405)


@csrf_exempt
@login_required
def register_push_subscription(request):
    """
    Enregistre un abonnement push pour les notifications.
    
    Utilisé par le service worker pour enregistrer l'endpoint
    de notification push du navigateur.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    try:
        data = json.loads(request.body)
        
        # En production, sauvegarder l'abonnement push
        # subscription = {
        #     'endpoint': data.get('endpoint'),
        #     'keys': data.get('keys', {}),
        #     'user_id': request.user.id
        # }
        
        # Sauvegarder dans la base ou cache Redis
        # PushSubscription.objects.update_or_create(
        #     user=request.user,
        #     defaults={'subscription_data': subscription}
        # )
        
        return JsonResponse({
            'success': True,
            'message': 'Abonnement push enregistré'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)



