"""
Vues pour la gestion des abonnements chauffeur par les particuliers et chauffeurs.
"""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView, TemplateView

from accounts.models import User, UserRoles
from core.models import NotificationLog
from .models import ChauffeurSubscription, ChauffeurSubscriptionRequest, Subscription, SubscriptionRequestStatus


class ManageChauffeurSubscriptionsView(LoginRequiredMixin, TemplateView):
    """
    Vue pour le particulier pour gérer tous ses abonnements chauffeur.
    """
    template_name = "subscriptions/manage_chauffeur_subscriptions.html"
    
    def dispatch(self, request, *args, **kwargs):
        if request.user.role != UserRoles.PARENT:
            messages.error(request, "Accès réservé aux particuliers.")
            return redirect("core:dashboard")
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Récupérer tous les abonnements chauffeur actifs
        active_subscriptions = ChauffeurSubscription.objects.filter(
            parent=user,
            status='active'
        ).select_related('chauffeur', 'subscription_request').order_by('-created_at')
        
        # Récupérer les demandes en attente
        pending_requests = ChauffeurSubscriptionRequest.objects.filter(
            parent=user,
            status__in=['pending', 'payment_pending']
        ).select_related('chauffeur').order_by('-created_at')
        
        # Récupérer l'historique (annulés, expirés)
        history = ChauffeurSubscription.objects.filter(
            parent=user,
            status__in=['cancelled', 'expired']
        ).select_related('chauffeur').order_by('-updated_at')[:10]
        
        context.update({
            'active_subscriptions': active_subscriptions,
            'pending_requests': pending_requests,
            'history': history,
            'total_active': active_subscriptions.count(),
        })
        
        return context


class ManageSubscribersView(LoginRequiredMixin, TemplateView):
    """
    Vue pour le chauffeur pour gérer tous ses abonnés.
    """
    template_name = "subscriptions/manage_subscribers.html"
    
    def dispatch(self, request, *args, **kwargs):
        if request.user.role != UserRoles.CHAUFFEUR:
            messages.error(request, "Accès réservé aux chauffeurs.")
            return redirect("core:dashboard")
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Récupérer tous les abonnements actifs (particuliers abonnés)
        active_subscribers = ChauffeurSubscription.objects.filter(
            chauffeur=user,
            status='active'
        ).select_related('parent', 'subscription_request').order_by('-created_at')
        
        # Récupérer les demandes en attente
        pending_requests = ChauffeurSubscriptionRequest.objects.filter(
            chauffeur=user,
            status='pending'
        ).select_related('parent').order_by('-created_at')
        
        # Récupérer l'historique
        history = ChauffeurSubscription.objects.filter(
            chauffeur=user,
            status__in=['cancelled', 'expired']
        ).select_related('parent').order_by('-updated_at')[:10]
        
        context.update({
            'active_subscribers': active_subscribers,
            'pending_requests': pending_requests,
            'history': history,
            'total_active': active_subscribers.count(),
        })
        
        return context


@login_required
@require_POST
def cancel_chauffeur_subscription(request, subscription_id):
    """
    Annuler un abonnement chauffeur.
    Peut être fait par le particulier ou le chauffeur.
    """
    subscription = get_object_or_404(ChauffeurSubscription, id=subscription_id)
    
    # Vérifier que l'utilisateur est bien partie prenante
    if request.user not in [subscription.parent, subscription.chauffeur]:
        return JsonResponse({
            'success': False,
            'error': 'Accès non autorisé'
        }, status=403)
    
    # Vérifier que l'abonnement est bien actif
    if subscription.status not in ['active', SubscriptionRequestStatus.ACTIVE]:
        return JsonResponse({
            'success': False,
            'error': f'Cet abonnement ne peut pas être annulé (statut actuel: {subscription.status})'
        }, status=400)
    
    try:
        # Annuler l'abonnement
        subscription.cancel(cancelled_by=request.user)
        
        # Notifier l'autre partie
        if request.user == subscription.parent:
            # Notifier le chauffeur
            recipient = subscription.chauffeur
            message = f"{request.user.get_full_name()} a annulé son abonnement '{subscription.title}'."
        else:
            # Notifier le particulier
            recipient = subscription.parent
            message = f"Le chauffeur {request.user.get_full_name()} a annulé l'abonnement '{subscription.title}'."
        
        # Créer la notification
        NotificationLog.objects.create(
            user=recipient,
            message=message,
            notification_type="subscription_cancelled",
            is_read=False
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Abonnement annulé avec succès'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def delete_chauffeur_subscription_record(request, subscription_id):
    """
    Supprimer un enregistrement d'abonnement annulé/expiré de la liste de l'utilisateur.
    Ne supprime pas réellement l'abonnement, juste le masque pour l'utilisateur.
    """
    subscription = get_object_or_404(ChauffeurSubscription, id=subscription_id)
    
    # Vérifier que l'utilisateur est bien partie prenante
    if request.user not in [subscription.parent, subscription.chauffeur]:
        return JsonResponse({
            'success': False,
            'error': 'Accès non autorisé'
        }, status=403)
    
    # Vérifier que l'abonnement est bien annulé ou expiré
    if subscription.status not in ['cancelled', 'expired']:
        return JsonResponse({
            'success': False,
            'error': 'Seuls les abonnements annulés ou expirés peuvent être supprimés de votre liste'
        }, status=400)
    
    try:
        # Pour l'instant, on supprime réellement l'enregistrement
        # Dans une version future, on pourrait ajouter des flags "hidden_for_parent" / "hidden_for_chauffeur"
        subscription.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Abonnement supprimé de votre liste'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def accept_subscription_request(request, request_id):
    """
    Accepter une demande d'abonnement.
    """
    subscription_request = get_object_or_404(ChauffeurSubscriptionRequest, id=request_id)
    
    # Vérifier que l'utilisateur est bien le chauffeur destinataire
    if request.user != subscription_request.chauffeur:
        return JsonResponse({
            'success': False,
            'error': 'Accès non autorisé'
        }, status=403)
    
    # Vérifier que la demande est bien en attente
    if subscription_request.status != 'pending':
        return JsonResponse({
            'success': False,
            'error': 'Cette demande a déjà été traitée'
        }, status=400)
    
    try:
        # Accepter la demande
        subscription_request.status = 'accepted'
        subscription_request.responded_at = timezone.now()
        subscription_request.chauffeur_response = request.POST.get('response_message', '')
        subscription_request.save()
        
        # Créer l'abonnement actif
        ChauffeurSubscription.objects.create(
            subscription_request=subscription_request,
            parent=subscription_request.parent,
            chauffeur=subscription_request.chauffeur,
            title=subscription_request.title,
            pickup_location=subscription_request.pickup_location,
            dropoff_location=subscription_request.dropoff_location,
            pickup_time=subscription_request.pickup_time,
            return_time=subscription_request.return_time,
            frequency=subscription_request.frequency,
            specific_days=subscription_request.specific_days,
            price_monthly=subscription_request.proposed_price_monthly,
            child_name=subscription_request.child_name,
            special_requirements=subscription_request.special_requirements,
            status='active',
            start_date=timezone.now().date(),
            next_billing_date=timezone.now().date() + timezone.timedelta(days=30)
        )
        
        # Notifier le particulier
        NotificationLog.objects.create(
            user=subscription_request.parent,
            message=f"Le chauffeur {request.user.get_full_name()} a accepté votre demande d'abonnement '{subscription_request.title}'.",
            notification_type="subscription_accepted",
            is_read=False
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Demande acceptée avec succès'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def reject_subscription_request(request, request_id):
    """
    Refuser une demande d'abonnement.
    """
    subscription_request = get_object_or_404(ChauffeurSubscriptionRequest, id=request_id)
    
    # Vérifier que l'utilisateur est bien le chauffeur destinataire
    if request.user != subscription_request.chauffeur:
        return JsonResponse({
            'success': False,
            'error': 'Accès non autorisé'
        }, status=403)
    
    # Vérifier que la demande est bien en attente
    if subscription_request.status != 'pending':
        return JsonResponse({
            'success': False,
            'error': 'Cette demande a déjà été traitée'
        }, status=400)
    
    try:
        # Refuser la demande
        subscription_request.status = 'rejected'
        subscription_request.responded_at = timezone.now()
        subscription_request.chauffeur_response = request.POST.get('response_message', '')
        subscription_request.save()
        
        # Notifier le particulier
        NotificationLog.objects.create(
            user=subscription_request.parent,
            message=f"Le chauffeur {request.user.get_full_name()} a refusé votre demande d'abonnement '{subscription_request.title}'.",
            notification_type="subscription_rejected",
            is_read=False
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Demande refusée'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def view_subscription_request_details(request, request_id):
    """
    Voir les détails d'une demande d'abonnement.
    """
    subscription_request = get_object_or_404(ChauffeurSubscriptionRequest, id=request_id)
    
    # Vérifier que l'utilisateur est bien partie prenante
    if request.user not in [subscription_request.parent, subscription_request.chauffeur]:
        return JsonResponse({
            'success': False,
            'error': 'Accès non autorisé'
        }, status=403)
    
    # Retourner les détails
    return JsonResponse({
        'success': True,
        'data': {
            'id': subscription_request.id,
            'title': subscription_request.title,
            'description': subscription_request.description,
            'parent_name': subscription_request.parent.get_full_name(),
            'chauffeur_name': subscription_request.chauffeur.get_full_name(),
            'pickup_location': subscription_request.pickup_location,
            'dropoff_location': subscription_request.dropoff_location,
            'pickup_time': subscription_request.pickup_time.strftime('%H:%M'),
            'return_time': subscription_request.return_time.strftime('%H:%M') if subscription_request.return_time else None,
            'frequency': subscription_request.get_frequency_display(),
            'proposed_price_monthly': float(subscription_request.proposed_price_monthly),
            'child_name': subscription_request.child_name,
            'special_requirements': subscription_request.special_requirements,
            'status': subscription_request.status,
            'created_at': subscription_request.created_at.strftime('%d/%m/%Y %H:%M'),
            'expires_at': subscription_request.expires_at.strftime('%d/%m/%Y %H:%M'),
            'chauffeur_response': subscription_request.chauffeur_response,
        }
    })


@login_required
def view_subscriber_details(request, subscription_id):
    """
    Voir les détails d'un abonnement actif.
    """
    subscription = get_object_or_404(ChauffeurSubscription, id=subscription_id)
    
    # Vérifier que l'utilisateur est bien partie prenante
    if request.user not in [subscription.parent, subscription.chauffeur]:
        return JsonResponse({
            'success': False,
            'error': 'Accès non autorisé'
        }, status=403)
    
    # Mapper la fréquence
    frequency_map = {
        'daily': 'Quotidien',
        'weekdays': 'Jours de semaine',
        'weekly': 'Hebdomadaire',
        'custom': 'Personnalisé',
    }
    frequency_display = frequency_map.get(subscription.frequency, subscription.frequency)
    
    # Retourner les détails
    return JsonResponse({
        'success': True,
        'data': {
            'id': subscription.id,
            'title': subscription.title,
            'parent_name': subscription.parent.get_full_name(),
            'parent_phone': subscription.parent.phone if hasattr(subscription.parent, 'phone') else '',
            'chauffeur_name': subscription.chauffeur.get_full_name(),
            'pickup_location': subscription.pickup_location,
            'dropoff_location': subscription.dropoff_location,
            'pickup_time': subscription.pickup_time.strftime('%H:%M'),
            'return_time': subscription.return_time.strftime('%H:%M') if subscription.return_time else None,
            'frequency': frequency_display,
            'price_monthly': float(subscription.price_monthly),
            'child_name': subscription.child_name,
            'special_requirements': subscription.special_requirements,
            'status': subscription.status,
            'start_date': subscription.start_date.strftime('%d/%m/%Y') if subscription.start_date else None,
            'next_billing_date': subscription.next_billing_date.strftime('%d/%m/%Y') if subscription.next_billing_date else None,
        }
    })

