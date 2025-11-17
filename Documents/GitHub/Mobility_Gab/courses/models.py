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


class TripRating(models.Model):
    """
    Évaluations mutuelles après chaque trajet (modèle Heetch).
    Permet aux chauffeurs et particuliers de s'évaluer mutuellement.
    """
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='ratings')
    rater = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='ratings_given'
    )
    rated = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='ratings_received'
    )
    
    # Note sur 5 étoiles
    stars = models.PositiveSmallIntegerField(
        choices=[(i, f"{i} étoile{'s' if i > 1 else ''}") for i in range(1, 6)],
        help_text="Note de 1 à 5 étoiles"
    )
    
    # Questions rapides (max 3 - modèle Heetch)
    was_on_time = models.BooleanField(
        null=True, 
        blank=True,
        verbose_name="À l'heure",
        help_text="Est arrivé(e) à l'heure ?"
    )
    was_polite = models.BooleanField(
        null=True, 
        blank=True,
        verbose_name="Courtois(e)",
        help_text="A été courtois(e) et respectueux(se) ?"
    )
    was_safe = models.BooleanField(
        null=True, 
        blank=True,
        verbose_name="Conduite sûre",
        help_text="Conduite sûre et confortable ? (pour chauffeur)"
    )
    vehicle_clean = models.BooleanField(
        null=True, 
        blank=True,
        verbose_name="Véhicule propre",
        help_text="Véhicule propre et en bon état ? (pour chauffeur)"
    )
    
    # Commentaire optionnel
    comment = models.TextField(
        max_length=500, 
        blank=True,
        verbose_name="Commentaire",
        help_text="Commentaire optionnel (max 500 caractères)"
    )
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = [['trip', 'rater', 'rated']]
        verbose_name = "Évaluation de trajet"
        verbose_name_plural = "Évaluations de trajets"
    
    def __str__(self):
        return f"Évaluation de {self.rater.get_full_name()} → {self.rated.get_full_name()} ({self.stars}★)"
    
    @property
    def is_chauffeur_rating(self):
        """Vérifie si c'est une évaluation d'un chauffeur."""
        return self.rated.role == 'chauffeur'
    
    @property
    def is_parent_rating(self):
        """Vérifie si c'est une évaluation d'un particulier."""
        return self.rated.role == 'parent'


