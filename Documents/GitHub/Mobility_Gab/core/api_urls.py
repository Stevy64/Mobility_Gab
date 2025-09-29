"""DRF API routing for Mobility Gab."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts import api_views as accounts_api
from subscriptions import api_views as subscriptions_api

router = DefaultRouter()
router.register(r"users", accounts_api.UserViewSet, basename="user")
router.register(r"profiles", accounts_api.ProfileViewSet, basename="profile")
router.register(r"chauffeurs", accounts_api.ChauffeurViewSet, basename="chauffeur")
router.register(r"parents", accounts_api.ParentViewSet, basename="parent")
router.register(r"plans", subscriptions_api.SubscriptionPlanViewSet, basename="subscription-plan")
router.register(r"subscriptions", subscriptions_api.SubscriptionViewSet, basename="subscription")
router.register(r"payments", subscriptions_api.PaymentViewSet, basename="payment")
router.register(r"trips", subscriptions_api.TripViewSet, basename="trip")
router.register(r"checkpoints", subscriptions_api.CheckpointViewSet, basename="checkpoint")
router.register(r"ratings", subscriptions_api.RatingViewSet, basename="rating")
router.register(r"notifications", subscriptions_api.NotificationViewSet, basename="notification")
router.register(r"sos-alerts", subscriptions_api.SOSAlertViewSet, basename="sos-alert")


urlpatterns = [
    path("", include(router.urls)),
    path("auth/", include("rest_framework.urls")),
    path("auth/token/", accounts_api.TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", accounts_api.TokenRefreshView.as_view(), name="token_refresh"),
    path("payments/mobilemoney/webhook/", subscriptions_api.MobileMoneyWebhookView.as_view(), name="mobilemoney-webhook"),
    path("payments/stripe/webhook/", subscriptions_api.StripeWebhookView.as_view(), name="stripe-webhook"),
]


