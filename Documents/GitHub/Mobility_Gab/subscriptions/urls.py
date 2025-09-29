"""URL routes for subscription-related pages."""

from django.urls import path

from . import views, views_premium
from . import views_advanced


app_name = "subscriptions"

urlpatterns = [
    # Demandes de course classiques
    path("ride-requests/new/", views.ParentRideRequestCreateView.as_view(), name="ride_request_create"),
    path("ride-requests/parent/", views.ParentRideRequestListView.as_view(), name="ride_requests_parent"),
    path("ride-requests/parent/<int:pk>/", views.ParentRideRequestDetailView.as_view(), name="ride_request_parent_detail"),
    path("ride-requests/chauffeur/", views.ChauffeurRideRequestInboxView.as_view(), name="ride_requests_chauffeur"),
    path("ride-requests/chauffeur/<int:pk>/<str:action>/", views.chauffeur_ride_request_action, name="ride_request_chauffeur_action"),
    
    # Demandes de course avancées avec géolocalisation
    path("ride-requests/advanced/", views_advanced.AdvancedRideRequestCreateView.as_view(), name="ride_request_advanced"),
    path("ride-requests/<int:pk>/waiting/", views_advanced.RideRequestWaitingView.as_view(), name="ride_request_waiting"),
    path("ride-requests/<int:pk>/accept/", views_advanced.accept_ride_request_advanced, name="accept_ride_request_advanced"),
    path("ride-requests/<int:pk>/decline/", views_advanced.decline_ride_request_advanced, name="decline_ride_request_advanced"),
    path("api/ride-requests/<int:pk>/status/", views_advanced.ride_request_status_api, name="ride_request_status_api"),
    path("api/ride-requests/<int:pk>/cancel/", views_advanced.cancel_ride_request_api, name="cancel_ride_request_api"),
    path("api/ride-requests/realtime/", views_advanced.get_ride_requests_realtime, name="ride_requests_realtime"),
    path("api/parent/ride-requests/status/", views_advanced.get_parent_ride_requests_status, name="parent_ride_requests_status"),
    path("api/chauffeur/availability/", views_advanced.toggle_chauffeur_availability, name="toggle_chauffeur_availability"),
    path("api/chauffeur/notifications/", views_advanced.get_chauffeur_notifications, name="chauffeur_notifications"),
    path("chauffeur_ride_requests_realtime/", views_advanced.ChauffeurRideRequestsRealtimeView.as_view(), name="chauffeur_ride_requests_realtime"),
    
    # Suivi GPS en temps réel
    path("tracking/<int:pk>/", views.TripTrackingView.as_view(), name="trip_tracking"),
    
    # Historique et statistiques
    path("history/", views.TripHistoryView.as_view(), name="trip_history"),
    path("trip/<int:trip_id>/details/", views.trip_details_ajax, name="trip_details_ajax"),
    path("export/history/", views.export_trip_history, name="export_trip_history"),
    
    # Gestion Premium Mobility Plus
    path("upgrade-premium/<int:subscription_id>/", views_premium.upgrade_to_premium, name="upgrade_to_premium"),
    path("downgrade-premium/<int:subscription_id>/", views_premium.downgrade_from_premium, name="downgrade_from_premium"),
    path("manage/<int:subscription_id>/", views_premium.SubscriptionManageView.as_view(), name="manage_subscription"),
    path("create/", views_premium.create_subscription, name="create_subscription"),
    path("api/available-chauffeurs/", views_premium.get_available_chauffeurs, name="available_chauffeurs"),
    
    # Suppression d'abonnements (anciens)
    path("delete/<int:subscription_id>/", views.delete_subscription, name="delete_subscription"),
    
    # === NOUVEAU SYSTÈME D'ABONNEMENTS ===
    path("", views.NewSubscriptionSystemView.as_view(), name="new_subscription_system"),
    path("mobility-plus/subscribe/", views.mobility_plus_subscribe, name="mobility_plus_subscribe"),
    path("mobility-plus/unsubscribe/", views.mobility_plus_unsubscribe, name="mobility_plus_unsubscribe"),
    path("mobility-plus/activate/", views.mobility_plus_activate, name="mobility_plus_activate"),
    path("payment/<int:payment_id>/", views.PaymentPageView.as_view(), name="payment_page"),
    path("payment/process/<int:payment_id>/", views.process_payment, name="process_payment"),
    path("chauffeur-respond/<int:request_id>/", views.chauffeur_respond_to_request, name="chauffeur_respond_to_request"),
    
    # === CHAT ===
    path("chat/", views.chat_list, name="chat_list"),
    path("chat/<int:user_id>/", views.chat_detail, name="chat_detail"),
    path("chat/send/", views.send_message, name="send_message"),
    
    # APIs pour le suivi GPS
    path("api/trips/<int:trip_id>/location/", views.trip_location_api, name="trip_location_api"),
    path("api/trips/<int:trip_id>/checkpoints/", views.trip_checkpoints_api, name="trip_checkpoints_api"),
    path("api/trips/<int:trip_id>/details/", views.trip_details_api, name="trip_details_api"),
    path("api/trips/export/", views.export_trip_history, name="export_trip_history"),
    path("api/chauffeur/location/", views.update_chauffeur_location, name="update_chauffeur_location"),
    path("api/trips/<int:trip_id>/checkpoint/", views.create_checkpoint, name="create_checkpoint"),
]
