"""
URLs pour la gestion des courses.
"""

from django.urls import path
from . import views

app_name = 'courses'

urlpatterns = [
    # Menu principal de gestion des courses
    path('', views.TripListView.as_view(), name='list'),
    path('menu/', views.CoursesMenuView.as_view(), name='menu'),
    
    # Vue des courses actives (la belle page !)
    path('actives/', views.ActiveTripsView.as_view(), name='active_trips'),
    
    # Gestion d'une course spécifique
    path('chauffeur/<int:pk>/', views.TripManagementView.as_view(), name='chauffeur_management'),
    path('particulier/<int:pk>/', views.TripManagementView.as_view(), name='particulier_management'),

    # Actions sur la course
    path('api/trip/<int:trip_id>/start/', views.start_trip, name='start_trip'),
    path('api/trip/<int:trip_id>/confirm/', views.confirm_trip_completion, name='confirm_trip_completion'),
    path('api/trip/<int:trip_id>/delete/', views.delete_trip, name='delete_trip'),

    # APIs pour le chat et les mises à jour
    path('api/trip/<int:trip_id>/messages/', views.get_messages, name='get_messages'),
    path('api/trip/<int:trip_id>/send-message/', views.send_message, name='send_message'),
    path('api/trip/<int:trip_id>/update-status/', views.update_trip_status, name='update_status'),
    
    # API pour marquer les notifications comme lues
    path('api/notifications/mark-read/', views.mark_notifications_read, name='mark_notifications_read'),
    
    # API pour marquer les messages comme lus
    path('api/trip/<int:trip_id>/mark-messages-read/', views.mark_messages_read, name='mark_messages_read'),
    
    # API pour archiver une course
    path('api/trip/<int:trip_id>/archive/', views.archive_trip, name='archive_trip'),
    
    # API pour récupérer la position GPS en temps réel
    path('api/trip/<int:trip_id>/gps-location/', views.get_trip_gps_location, name='get_trip_gps_location'),
    
    # Évaluation de trajet
    path('trip/<int:pk>/rate/', views.TripRatingView.as_view(), name='rate_trip'),
]
