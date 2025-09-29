"""
Système de notifications pour Mobility Gab.

Ce module gère l'envoi de notifications push, SMS et email
pour tenir les utilisateurs informés en temps réel.
"""

import json
import logging
from typing import List, Optional, Dict, Any
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import NotificationLog

User = get_user_model()
logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service centralisé pour l'envoi de notifications.
    
    Gère l'envoi de notifications via différents canaux :
    - Push notifications (via WebPush API)
    - SMS (via API externe)
    - Email
    - Notifications in-app
    """
    
    def __init__(self):
        self.sms_enabled = getattr(settings, 'SMS_ENABLED', False)
        self.push_enabled = getattr(settings, 'PUSH_NOTIFICATIONS_ENABLED', False)
        self.email_enabled = getattr(settings, 'EMAIL_NOTIFICATIONS_ENABLED', True)
    
    def send_notification(
        self,
        user: User,
        title: str,
        message: str,
        notification_type: str = "general",
        data: Optional[Dict[str, Any]] = None,
        channels: Optional[List[str]] = None
    ) -> NotificationLog:
        """
        Envoie une notification via les canaux spécifiés.
        
        Args:
            user: Utilisateur destinataire
            title: Titre de la notification
            message: Contenu du message
            notification_type: Type de notification (trip_update, payment, etc.)
            data: Données supplémentaires (JSON)
            channels: Canaux d'envoi ['push', 'sms', 'email', 'in_app']
                     Si None, utilise les préférences utilisateur
        
        Returns:
            NotificationLog: Log de la notification créée
        """
        # Déterminer les canaux à utiliser
        if channels is None:
            channels = self._get_user_preferred_channels(user)
        
        # Créer le log de notification
        notification_log = NotificationLog.objects.create(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
        )
        
        # Envoyer via chaque canal
        results = {}
        
        if 'in_app' in channels:
            results['in_app'] = True  # Déjà créé dans la DB
        
        if 'email' in channels and self.email_enabled:
            results['email'] = self._send_email(user, title, message, notification_type)
            notification_log.sent_via_email = results['email']
        
        if 'sms' in channels and self.sms_enabled:
            results['sms'] = self._send_sms(user, title, message)
            notification_log.sent_via_sms = results['sms']
        
        if 'push' in channels and self.push_enabled:
            results['push'] = self._send_push(user, title, message, data)
            notification_log.sent_via_push = results['push']
        
        # Mettre à jour le log
        notification_log.delivery_status = json.dumps(results)
        notification_log.save()
        
        logger.info(f"Notification envoyée à {user.username}: {title} via {channels}")
        
        return notification_log
    
    def _get_user_preferred_channels(self, user: User) -> List[str]:
        """
        Détermine les canaux préférés de l'utilisateur.
        """
        channels = ['in_app']  # Toujours actif
        
        if hasattr(user, 'profile'):
            if user.profile.push_notifications_enabled:
                channels.append('push')
            if user.profile.sms_notifications_enabled:
                channels.append('sms')
        
        # Email activé par défaut sauf désactivation explicite
        channels.append('email')
        
        return channels
    
    def _send_email(self, user: User, title: str, message: str, notification_type: str) -> bool:
        """
        Envoie une notification par email.
        """
        try:
            # Template email personnalisé selon le type
            template_name = f'emails/{notification_type}.html'
            
            # Contexte pour le template
            context = {
                'user': user,
                'title': title,
                'message': message,
                'site_name': 'Mobility Gab',
                'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000'),
            }
            
            # Essayer d'utiliser un template spécifique, sinon template générique
            try:
                html_content = render_to_string(template_name, context)
            except:
                html_content = render_to_string('emails/generic.html', context)
            
            send_mail(
                subject=f"[Mobility Gab] {title}",
                message=message,  # Version texte
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_content,
                fail_silently=False,
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Erreur envoi email à {user.email}: {e}")
            return False
    
    def _send_sms(self, user: User, title: str, message: str) -> bool:
        """
        Envoie une notification par SMS.
        
        Note: Implémentation mock. En production, intégrer avec un service
        comme Twilio, AWS SNS, ou un opérateur local.
        """
        try:
            phone = getattr(user.profile, 'phone', None) if hasattr(user, 'profile') else None
            
            if not phone:
                logger.warning(f"Pas de numéro de téléphone pour {user.username}")
                return False
            
            # Mock SMS - en production, remplacer par vraie API
            sms_content = f"{title}: {message}"
            
            # Exemple d'intégration Twilio (commenté)
            # from twilio.rest import Client
            # client = Client(settings.TWILIO_SID, settings.TWILIO_TOKEN)
            # client.messages.create(
            #     body=sms_content,
            #     from_=settings.TWILIO_PHONE,
            #     to=phone
            # )
            
            logger.info(f"SMS mock envoyé à {phone}: {sms_content}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur envoi SMS à {user.username}: {e}")
            return False
    
    def _send_push(self, user: User, title: str, message: str, data: Optional[Dict] = None) -> bool:
        """
        Envoie une notification push.
        
        Note: Implémentation mock. En production, intégrer avec Firebase Cloud Messaging
        ou Web Push Protocol.
        """
        try:
            # Mock push notification
            push_data = {
                'title': title,
                'body': message,
                'icon': '/static/icons/notification-icon.png',
                'badge': '/static/icons/badge-icon.png',
                'data': data or {},
                'actions': [
                    {'action': 'view', 'title': 'Voir'},
                    {'action': 'dismiss', 'title': 'Ignorer'}
                ]
            }
            
            # En production, utiliser Firebase ou Web Push
            # import firebase_admin
            # from firebase_admin import messaging
            # 
            # message = messaging.Message(
            #     notification=messaging.Notification(title=title, body=message),
            #     data=data or {},
            #     token=user_device_token
            # )
            # messaging.send(message)
            
            logger.info(f"Push notification mock envoyée à {user.username}: {title}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur envoi push à {user.username}: {e}")
            return False


# Instance globale du service
notification_service = NotificationService()


def send_trip_notification(user: User, trip_status: str, chauffeur_name: str = "", **kwargs):
    """
    Envoie une notification liée à une course.
    
    Args:
        user: Utilisateur à notifier
        trip_status: Statut de la course (en_route, arrive, depose, etc.)
        chauffeur_name: Nom du chauffeur
        **kwargs: Données supplémentaires
    """
    messages = {
        'en_route': f"{chauffeur_name} est en route vers vous",
        'arrive': f"{chauffeur_name} est arrivé à votre position",
        'depose': "Vous avez été déposé à destination",
        'termine': "Course terminée avec succès",
        'annule': "Course annulée",
    }
    
    title = "Mise à jour de votre course"
    message = messages.get(trip_status, f"Statut de course: {trip_status}")
    
    return notification_service.send_notification(
        user=user,
        title=title,
        message=message,
        notification_type="trip_update",
        data={'trip_status': trip_status, 'chauffeur': chauffeur_name, **kwargs}
    )


def send_payment_notification(user: User, payment_status: str, amount: float = 0, **kwargs):
    """
    Envoie une notification liée à un paiement.
    """
    messages = {
        'success': f"Paiement de {amount} FCFA confirmé",
        'failed': f"Échec du paiement de {amount} FCFA",
        'pending': f"Paiement de {amount} FCFA en cours",
        'overdue': f"Paiement de {amount} FCFA en retard",
    }
    
    title = "Notification de paiement"
    message = messages.get(payment_status, f"Statut de paiement: {payment_status}")
    
    return notification_service.send_notification(
        user=user,
        title=title,
        message=message,
        notification_type="payment",
        data={'payment_status': payment_status, 'amount': amount, **kwargs}
    )


def send_sos_alert(user: User, location: str = "", **kwargs):
    """
    Envoie une alerte SOS urgente.
    """
    title = "🚨 ALERTE SOS"
    message = f"Alerte d'urgence déclenchée par {user.get_full_name() or user.username}"
    
    if location:
        message += f" à {location}"
    
    # SOS = notification prioritaire via tous les canaux
    return notification_service.send_notification(
        user=user,
        title=title,
        message=message,
        notification_type="sos",
        data={'location': location, 'timestamp': timezone.now().isoformat(), **kwargs},
        channels=['in_app', 'email', 'sms', 'push']  # Tous les canaux
    )
