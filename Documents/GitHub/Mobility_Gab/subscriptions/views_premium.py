"""
Vues pour la gestion des fonctionnalités Mobility Plus.

Ce fichier contient les vues liées à l'upgrade/downgrade vers Mobility Plus,
la gestion des abonnements premium et les fonctionnalités associées.
"""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.views import View
from django.contrib import messages
from django.utils import timezone
from decimal import Decimal

from accounts.models import UserRoles
from .models import Subscription, SubscriptionPlan


@login_required
def upgrade_to_premium(request, subscription_id):
    """
    Upgrade d'un abonnement vers Mobility Plus.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    try:
        subscription = get_object_or_404(Subscription, id=subscription_id)
        
        # Vérifier que l'utilisateur a le droit de modifier cet abonnement
        if request.user.role == UserRoles.PARENT and subscription.parent != request.user:
            return JsonResponse({'success': False, 'error': 'Accès refusé'})
        elif request.user.role == UserRoles.CHAUFFEUR and subscription.chauffeur != request.user:
            return JsonResponse({'success': False, 'error': 'Accès refusé'})
        
        # Vérifier si l'abonnement n'est pas déjà premium
        if hasattr(subscription, 'has_mobility_plus') and subscription.has_mobility_plus:
            return JsonResponse({'success': False, 'error': 'Cet abonnement est déjà Mobility Plus'})
        
        # Calculer le nouveau prix (ajout de 5000 FCFA)
        premium_fee = Decimal('5000.00')
        new_price = subscription.price_monthly + premium_fee
        
        # Mettre à jour l'abonnement
        subscription.price_monthly = new_price
        
        # Ajouter le champ Mobility Plus si le modèle le supporte
        if hasattr(subscription, 'has_mobility_plus'):
            subscription.has_mobility_plus = True
        
        # Ajouter une note sur l'upgrade
        upgrade_note = f"Upgrade vers Mobility Plus le {timezone.now().strftime('%d/%m/%Y')} (+{premium_fee} FCFA/mois)"
        if subscription.notes:
            subscription.notes += f"\n{upgrade_note}"
        else:
            subscription.notes = upgrade_note
        
        subscription.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Abonnement upgradé vers Mobility Plus avec succès',
            'new_price': float(new_price)
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def downgrade_from_premium(request, subscription_id):
    """
    Downgrade d'un abonnement depuis Mobility Plus.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    try:
        subscription = get_object_or_404(Subscription, id=subscription_id)
        
        # Vérifier que l'utilisateur a le droit de modifier cet abonnement
        if request.user.role == UserRoles.PARENT and subscription.parent != request.user:
            return JsonResponse({'success': False, 'error': 'Accès refusé'})
        elif request.user.role == UserRoles.CHAUFFEUR and subscription.chauffeur != request.user:
            return JsonResponse({'success': False, 'error': 'Accès refusé'})
        
        # Vérifier si l'abonnement est premium
        if hasattr(subscription, 'has_mobility_plus') and not subscription.has_mobility_plus:
            return JsonResponse({'success': False, 'error': 'Cet abonnement n\'est pas Mobility Plus'})
        
        # Calculer le nouveau prix (retrait de 5000 FCFA)
        premium_fee = Decimal('5000.00')
        new_price = max(subscription.price_monthly - premium_fee, subscription.plan.price_monthly)
        
        # Mettre à jour l'abonnement
        subscription.price_monthly = new_price
        
        # Retirer le statut Mobility Plus si le modèle le supporte
        if hasattr(subscription, 'has_mobility_plus'):
            subscription.has_mobility_plus = False
        
        # Ajouter une note sur le downgrade
        downgrade_note = f"Downgrade depuis Mobility Plus le {timezone.now().strftime('%d/%m/%Y')} (-{premium_fee} FCFA/mois)"
        if subscription.notes:
            subscription.notes += f"\n{downgrade_note}"
        else:
            subscription.notes = downgrade_note
        
        subscription.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Abonnement rétrogradé avec succès',
            'new_price': float(new_price)
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


class SubscriptionManageView(LoginRequiredMixin, View):
    """
    Vue pour la gestion détaillée d'un abonnement.
    """
    
    def get(self, request, subscription_id):
        """Afficher la page de gestion d'un abonnement."""
        subscription = get_object_or_404(Subscription, id=subscription_id)
        
        # Vérifier les permissions
        if request.user.role == UserRoles.PARENT and subscription.parent != request.user:
            messages.error(request, "Vous n'avez pas accès à cet abonnement.")
            return redirect('core:dashboard')
        elif request.user.role == UserRoles.CHAUFFEUR and subscription.chauffeur != request.user:
            messages.error(request, "Vous n'avez pas accès à cet abonnement.")
            return redirect('core:dashboard')
        
        # Récupérer les données de l'abonnement
        context = {
            'subscription': subscription,
            'recent_trips': subscription.trips.all().order_by('-scheduled_date')[:10],
            'payment_history': subscription.payments.all().order_by('-created_at')[:10],
            'is_premium': hasattr(subscription, 'has_mobility_plus') and subscription.has_mobility_plus,
        }
        
        return render(request, 'subscriptions/subscription_manage.html', context)


@login_required
def create_subscription(request):
    """
    Créer un nouvel abonnement.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    if request.user.role != UserRoles.PARENT:
        return JsonResponse({'success': False, 'error': 'Seuls les particuliers peuvent créer des abonnements'})
    
    try:
        plan_id = request.POST.get('plan_id')
        chauffeur_id = request.POST.get('chauffeur_id')
        mobility_plus = request.POST.get('mobility_plus') == 'on'
        
        # Récupérer le plan
        plan = get_object_or_404(SubscriptionPlan, id=plan_id)
        
        # Récupérer le chauffeur si spécifié
        chauffeur = None
        if chauffeur_id:
            from accounts.models import User
            chauffeur = get_object_or_404(User, id=chauffeur_id, role=UserRoles.CHAUFFEUR)
        
        # Calculer le prix
        price = plan.price_monthly
        if mobility_plus:
            price += Decimal('5000.00')
        
        # Calculer la prochaine date de paiement
        next_due_date = timezone.now().date() + timezone.timedelta(days=30)
        
        # Créer l'abonnement
        subscription = Subscription.objects.create(
            parent=request.user,
            chauffeur=chauffeur,
            plan=plan,
            price_monthly=price,
            next_due_date=next_due_date,
            status='active'
        )
        
        # Ajouter Mobility Plus si demandé
        if mobility_plus and hasattr(subscription, 'has_mobility_plus'):
            subscription.has_mobility_plus = True
            subscription.notes = "Abonnement créé avec Mobility Plus"
            subscription.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Abonnement créé avec succès',
            'subscription_id': subscription.id
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_available_chauffeurs(request):
    """
    Récupérer la liste des chauffeurs disponibles pour un nouvel abonnement.
    """
    try:
        from accounts.models import User
        
        chauffeurs = User.objects.filter(
            role=UserRoles.CHAUFFEUR,
            is_active=True
        ).select_related('profile', 'chauffeur_profile')
        
        # Filtrer les chauffeurs qui ne sont pas surchargés
        available_chauffeurs = []
        for chauffeur in chauffeurs:
            active_subscriptions = Subscription.objects.filter(
                chauffeur=chauffeur,
                status='active'
            ).count()
            
            # Limite arbitraire de 10 abonnements par chauffeur
            if active_subscriptions < 10:
                available_chauffeurs.append({
                    'id': chauffeur.id,
                    'name': chauffeur.get_full_name(),
                    'rating': getattr(chauffeur.chauffeur_profile, 'reliability_score', 5.0) if hasattr(chauffeur, 'chauffeur_profile') else 5.0,
                    'active_subscriptions': active_subscriptions,
                    'vehicle': f"{getattr(chauffeur.chauffeur_profile, 'vehicle_make', '')} {getattr(chauffeur.chauffeur_profile, 'vehicle_model', '')}" if hasattr(chauffeur, 'chauffeur_profile') else "Non spécifié"
                })
        
        return JsonResponse({
            'success': True,
            'chauffeurs': available_chauffeurs
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
