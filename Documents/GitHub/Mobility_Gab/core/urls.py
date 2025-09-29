"""URL configuration for core app."""

from django.urls import path

from . import views, api_views


app_name = "core"

urlpatterns = [
    # Pages principales
    path("", views.LandingView.as_view(), name="landing"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("dashboard/redirect/", views.DashboardRedirectView.as_view(), name="dashboard_redirect"),
    path("dashboard/parent/", views.ParentDashboardView.as_view(), name="parent_dashboard"),
    path("dashboard/particulier/", views.ParticulierDashboardView.as_view(), name="particulier_dashboard"),
    path("dashboard/chauffeur/", views.ChauffeurDashboardView.as_view(), name="chauffeur_dashboard"),
    path("dashboard/admin/", views.AdminDashboardView.as_view(), name="admin_dashboard"),
    path("onboarding/success/", views.OnboardingSuccessView.as_view(), name="onboarding_success"),
    
    # APIs pour notifications et polling
    path("api/sos/", api_views.create_sos_alert, name="create_sos_alert"),
    path("api/polling/", api_views.polling_updates, name="polling_updates"),
    path("api/notifications/preferences/", api_views.notification_preferences, name="notification_preferences"),
    path("api/push/subscribe/", api_views.register_push_subscription, name="register_push_subscription"),
]


