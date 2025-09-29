"""
URLs pour la gestion des courses.
"""

from django.urls import path
from . import views

app_name = 'courses'

urlpatterns = [
    # Menu principal de gestion des courses
    path('', views.CoursesMenuView.as_view(), name='menu'),
    
    # Vue des courses actives (la belle page !)
    path('actives/', views.ActiveTripsView.as_view(), name='active_trips'),
    
    # Gestion d'une course spécifique
    path('chauffeur/<int:pk>/', views.TripManagementView.as_view(), name='chauffeur_management'),
    path('particulier/<int:pk>/', views.TripManagementView.as_view(), name='particulier_management'),
    
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
]
