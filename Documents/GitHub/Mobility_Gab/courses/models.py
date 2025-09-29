"""
Modèles pour la gestion des courses en temps réel.
"""

from django.db import models
from django.conf import settings
from django.utils import timezone
from subscriptions.models import Trip


class TripMessage(models.Model):
    """
    Messages du chat entre chauffeur et particulier pendant la course.
    Disponible uniquement avec l'abonnement Mobility Plus.
    """
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField(max_length=500)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['timestamp']
    
    def __str__(self):
        return f"Message de {self.sender.get_full_name()} - {self.timestamp}"
    
    def mark_as_read_by(self, user):
        """Marquer le message comme lu par un utilisateur spécifique."""
        # Version temporaire sans les nouveaux champs
        self.is_read = True
        self.save(update_fields=['is_read'])
    
    def is_read_by(self, user):
        """Vérifier si le message a été lu par un utilisateur spécifique."""
        # Version temporaire - retourne toujours True si is_read est True
        return self.is_read


class TripUpdate(models.Model):
    """
    Mises à jour de statut pendant la course.
    """
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='updates')
    update_type = models.CharField(max_length=50, choices=[
        ('started', 'Course commencée'),
        ('pickup', 'Arrivé au point de départ'),
        ('passenger_picked', 'Passager récupéré'),
        ('destination_reached', 'Arrivé à destination'),
        ('completed', 'Course terminée'),
        ('issue', 'Problème signalé'),
        ('delay', 'Retard signalé'),
    ])
    message = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.get_update_type_display()} - {self.trip}"


