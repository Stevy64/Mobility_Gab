"""
Serializers pour l'application Core.

Ce fichier contient les serializers pour les notifications,
les alertes SOS, et autres données de l'application core.
"""

from rest_framework import serializers
from .models import NotificationLog, SOSAlert


class NotificationSerializer(serializers.ModelSerializer):
    """
    Serializer pour les notifications utilisateur.
    
    Sérialise les notifications avec les informations essentielles
    pour l'affichage dans l'interface utilisateur.
    """
    
    # Champs calculés
    is_read = serializers.SerializerMethodField()
    time_ago = serializers.SerializerMethodField()
    
    class Meta:
        model = NotificationLog
        fields = [
            'id',
            'title',
            'message',
            'notification_type',
            'created_at',
            'read',
            'is_read',
            'time_ago',
            'sent_via_email',
            'sent_via_sms',
            'sent_via_push',
        ]
        read_only_fields = ['created_at', 'is_read', 'time_ago']
    
    def get_is_read(self, obj):
        """Indique si la notification a été lue."""
        return obj.read
    
    def get_time_ago(self, obj):
        """Retourne le temps écoulé depuis la création."""
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        diff = now - obj.created_at
        
        if diff < timedelta(minutes=1):
            return "À l'instant"
        elif diff < timedelta(hours=1):
            minutes = int(diff.total_seconds() / 60)
            return f"Il y a {minutes} min"
        elif diff < timedelta(days=1):
            hours = int(diff.total_seconds() / 3600)
            return f"Il y a {hours}h"
        elif diff < timedelta(days=7):
            days = diff.days
            return f"Il y a {days} jour{'s' if days > 1 else ''}"
        else:
            return obj.created_at.strftime('%d/%m/%Y')


class SOSAlertSerializer(serializers.ModelSerializer):
    """
    Serializer pour les alertes SOS.
    
    Sérialise les alertes d'urgence avec toutes les informations
    nécessaires pour la gestion des secours.
    """
    
    # Informations utilisateur
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_phone = serializers.CharField(source='user.profile.phone', read_only=True)
    
    # Informations de localisation
    location_display = serializers.SerializerMethodField()
    
    # Informations temporelles
    time_since_alert = serializers.SerializerMethodField()
    
    class Meta:
        model = SOSAlert
        fields = [
            'id',
            'user',
            'user_name',
            'user_phone',
            'latitude',
            'longitude',
            'location_display',
            'message',
            'trip_id',
            'status',
            'created_at',
            'resolved_at',
            'resolved_by',
            'time_since_alert',
        ]
        read_only_fields = ['created_at', 'user_name', 'user_phone', 'location_display', 'time_since_alert']
    
    def get_location_display(self, obj):
        """Formate l'affichage de la localisation."""
        if obj.latitude and obj.longitude:
            return f"{obj.latitude:.6f}, {obj.longitude:.6f}"
        return "Position non disponible"
    
    def get_time_since_alert(self, obj):
        """Calcule le temps écoulé depuis l'alerte."""
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        diff = now - obj.created_at
        
        if diff < timedelta(minutes=1):
            return "À l'instant"
        elif diff < timedelta(hours=1):
            minutes = int(diff.total_seconds() / 60)
            return f"{minutes} minutes"
        else:
            hours = int(diff.total_seconds() / 3600)
            return f"{hours} heures"


class NotificationPreferencesSerializer(serializers.Serializer):
    """
    Serializer pour les préférences de notification.
    
    Permet de gérer les préférences utilisateur pour
    les différents canaux de notification.
    """
    
    push_enabled = serializers.BooleanField(default=True)
    sms_enabled = serializers.BooleanField(default=False)
    email_enabled = serializers.BooleanField(default=True)
    
    # Préférences par type de notification
    trip_notifications = serializers.BooleanField(default=True)
    payment_notifications = serializers.BooleanField(default=True)
    marketing_notifications = serializers.BooleanField(default=False)
    
    def validate(self, data):
        """
        Valide les préférences de notification.
        """
        # Au moins un canal doit être activé pour les notifications importantes
        if not any([data.get('push_enabled'), data.get('email_enabled')]):
            raise serializers.ValidationError(
                "Au moins un canal de notification (push ou email) doit être activé."
            )
        
        return data


class PushSubscriptionSerializer(serializers.Serializer):
    """
    Serializer pour les abonnements push.
    
    Gère l'enregistrement des endpoints de notification push
    pour les navigateurs web.
    """
    
    endpoint = serializers.URLField(required=True)
    keys = serializers.DictField(required=True)
    
    def validate_keys(self, value):
        """
        Valide la structure des clés push.
        """
        required_keys = ['p256dh', 'auth']
        
        for key in required_keys:
            if key not in value:
                raise serializers.ValidationError(f"Clé '{key}' manquante dans les données push.")
        
        return value
