"""Core views for public landing and dashboards."""

from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import TemplateView

from django.contrib.auth import get_user_model

from accounts.models import ChauffeurBadge, UserRoles
from django.db.models import Count, Q

from subscriptions.models import Subscription, Trip, SubscriptionStatus

User = get_user_model()


class LandingView(TemplateView):
    template_name = "core/landing.html"


class OnboardingSuccessView(LoginRequiredMixin, TemplateView):
    template_name = "core/onboarding_success.html"


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard/base.html"

    def get_template_names(self):
        user = self.request.user
        role = user.role
        if user.is_staff and self.request.GET.get("view") in {UserRoles.PARENT, UserRoles.CHAUFFEUR}:
            role = self.request.GET.get("view")
        if role == UserRoles.PARENT:
            return ["core/dashboard/subscription_management.html"]
        if role == UserRoles.CHAUFFEUR:
            return ["core/dashboard/subscription_management.html"]
        if role == UserRoles.ADMIN or user.is_staff:
            return ["core/dashboard/admin_dashboard.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.now().date()

        target_user = user
        role = user.role
        if user.is_staff and self.request.GET.get("user_id"):
            try:
                target_user = User.objects.select_related("profile").get(id=self.request.GET["user_id"])
                role = target_user.role
            except User.DoesNotExist:
                target_user = user
                role = user.role

        if role == UserRoles.PARENT:
            # Récupérer seulement les abonnements actifs pour l'affichage
            subscriptions = Subscription.objects.filter(
                parent=target_user, 
                status="active"
            ).select_related('plan', 'chauffeur')
            
            # Récupérer les nouveaux abonnements (Mobility Plus et Chauffeur)
            from subscriptions.models import MobilityPlusSubscription, ChauffeurSubscription
            
            try:
                mobility_plus = target_user.mobility_plus_subscription
                has_mobility_plus = mobility_plus.is_active and mobility_plus.status == 'active'
            except:
                has_mobility_plus = False
                mobility_plus = None
            
            chauffeur_subscriptions = ChauffeurSubscription.objects.filter(
                parent=target_user,
                status='active'
            ).select_related('chauffeur')
            
            user_badges = []  # TODO: Implémenter le système de badges pour les particuliers
            
            context.update(
                {
                    "active_subscriptions": subscriptions.count(),
                    "subscriptions": subscriptions,
                    "mobility_plus": mobility_plus,
                    "has_mobility_plus": has_mobility_plus,
                    "chauffeur_subscriptions": chauffeur_subscriptions,
                    "user_badges": user_badges,
                    "next_due_date": subscriptions.order_by("next_due_date").values_list("next_due_date", flat=True).first(),
                    "dashboard_user": target_user,
                }
            )

        elif role == UserRoles.CHAUFFEUR:
            # Récupérer seulement les abonnements actifs pour l'affichage
            subscriptions = Subscription.objects.filter(
                chauffeur=target_user, 
                status="active"
            ).select_related('plan', 'parent')
            
            # Récupérer les nouveaux abonnements chauffeur
            from subscriptions.models import ChauffeurSubscription, ChauffeurSubscriptionRequest
            
            chauffeur_subscriptions = ChauffeurSubscription.objects.filter(
                chauffeur=target_user,
                status='active'
            ).select_related('parent')
            
            # Demandes en attente
            pending_requests = ChauffeurSubscriptionRequest.objects.filter(
                chauffeur=target_user,
                status='pending'
            ).select_related('parent')
            
            # Récupérer les badges du chauffeur
            user_badges = []
            try:
                if hasattr(target_user, 'chauffeur_profile'):
                    user_badges = ChauffeurBadge.objects.filter(chauffeur=target_user.chauffeur_profile).select_related("badge")
            except:
                user_badges = []
            
            context.update(
                {
                    "active_subscribers": subscriptions.count(),
                    "subscriptions": subscriptions,
                    "chauffeur_subscriptions": chauffeur_subscriptions,
                    "pending_requests": pending_requests,
                    "user_badges": user_badges,
                    "dashboard_user": target_user,
                }
            )

        elif role == UserRoles.ADMIN or user.is_staff:
            trips = Trip.objects.select_related("parent", "chauffeur").order_by("-scheduled_date", "-started_at")[:20]
            subscriptions = (
                Subscription.objects.select_related("parent", "chauffeur", "plan")
                .order_by("-start_date")[:20]
            )

            context.update(
                {
                    "kpis": {
                        "parents_count": Subscription.objects.values("parent").distinct().count(),
                        "active_drivers": Subscription.objects.filter(status=SubscriptionStatus.ACTIVE).values("chauffeur").distinct().count(),
                        "overdue_subscriptions": Subscription.objects.filter(status=SubscriptionStatus.OVERDUE).count(),
                        "suspended_accounts": Subscription.objects.filter(status=SubscriptionStatus.SUSPENDED).values("parent").distinct().count(),
                    },
                    "trip_segments": trips,
                    "subscription_segments": subscriptions,
                    "trip_filters": {
                        "in_progress": Trip.objects.filter(status="in_progress").count(),
                        "scheduled": Trip.objects.filter(status="scheduled").count(),
                        "completed_week": Trip.objects.filter(status="completed", completed_at__date__gte=today - timedelta(days=7)).count(),
                    },
                    "subscription_filters": {
                        "active": Subscription.objects.filter(status=SubscriptionStatus.ACTIVE).count(),
                        "overdue": Subscription.objects.filter(status=SubscriptionStatus.OVERDUE).count(),
                        "suspended": Subscription.objects.filter(status=SubscriptionStatus.SUSPENDED).count(),
                        "cancelled": Subscription.objects.filter(status=SubscriptionStatus.CANCELLED).count(),
                    },
                }
            )

        return context


class DashboardRedirectView(LoginRequiredMixin, TemplateView):
    """Redirect user to appropriate dashboard."""

    def get(self, request, *args, **kwargs):
        if request.user.role == UserRoles.PARENT:
            return redirect("core:parent_dashboard")
        if request.user.role == UserRoles.CHAUFFEUR:
            return redirect("core:chauffeur_dashboard")
        if request.user.role == UserRoles.ADMIN:
            return redirect("core:admin_dashboard")
        return redirect(reverse_lazy("core:landing"))


class ParentDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard/parent_dashboard_realtime.html"
    
    def dispatch(self, request, *args, **kwargs):
        """Vérifier que seuls les particuliers peuvent accéder."""
        if request.user.role != UserRoles.PARENT:
            messages.error(request, "Accès réservé aux particuliers.")
            return redirect("core:dashboard")
        return super().dispatch(request, *args, **kwargs)


class ParticulierDashboardView(LoginRequiredMixin, TemplateView):
    """Vue pour l'espace particulier avec dashboard temps réel."""
    template_name = "core/dashboard/particulier_dashboard.html"
    
    def dispatch(self, request, *args, **kwargs):
        """Vérifier que seuls les particuliers peuvent accéder."""
        if request.user.role != UserRoles.PARENT:
            messages.error(request, "Accès réservé aux particuliers.")
            return redirect("core:dashboard")
        return super().dispatch(request, *args, **kwargs)


class ChauffeurDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard/chauffeur_dashboard.html"


class AdminDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard/admin_dashboard.html"
