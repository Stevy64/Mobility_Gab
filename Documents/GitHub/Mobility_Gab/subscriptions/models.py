"""Models for managing subscriptions, trips and payments."""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Actif"
    OVERDUE = "overdue", "En retard"
    SUSPENDED = "suspended", "Suspendu"
    CANCELLED = "cancelled", "Annulé"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    SUCCESS = "success", "Réussi"
    FAILED = "failed", "Échoué"
    CANCELLED = "cancelled", "Annulé"


class RideRequestStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    ACCEPTED = "accepted", "Acceptée"
    DECLINED = "declined", "Refusée"
    CANCELLED = "cancelled", "Annulée"
    COMPLETED = "completed", "Terminée"


class SubscriptionPlan(models.Model):
    """Defines a type of subscription."""

    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    price_monthly = models.DecimalField(max_digits=9, decimal_places=2)
    trips_per_day = models.PositiveIntegerField(default=2)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name  # pragma: no cover


class Subscription(models.Model):
    """Subscription linking parent and driver."""

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        limit_choices_to={"role": "parent"},
    )
    chauffeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="assigned_subscriptions",
        limit_choices_to={"role": "chauffeur"},
    )
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    price_monthly = models.DecimalField(max_digits=9, decimal_places=2)
    start_date = models.DateField(auto_now_add=True)
    next_due_date = models.DateField()
    status = models.CharField(max_length=32, choices=SubscriptionStatus.choices, default=SubscriptionStatus.ACTIVE)
    last_payment_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    active_child_name = models.CharField(max_length=128, blank=True)
    pickup_location = models.CharField(max_length=255, blank=True)
    dropoff_location = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="subscriptions_created",
    )

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"Abonnement {self.parent} -> {self.chauffeur}"  # pragma: no cover

    def set_overdue(self):
        self.status = SubscriptionStatus.OVERDUE
        self.save(update_fields=["status"])

    def suspend(self, reason: str | None = None):
        self.status = SubscriptionStatus.SUSPENDED
        self.save(update_fields=["status"])
        if self.parent.is_suspended is False:
            self.parent.suspend(reason or "Abonnement en retard")

    def activate(self):
        self.status = SubscriptionStatus.ACTIVE
        self.save(update_fields=["status"])
        if self.parent.is_suspended:
            self.parent.lift_suspension()

    def extend_next_due_date(self, days: int = 30):
        self.next_due_date += timedelta(days=days)
        self.save(update_fields=["next_due_date"])


class Payment(models.Model):
    """Payments for subscriptions."""

    METHOD_CHOICES = [
        ("mobile_money", "Mobile Money"),
        ("stripe", "Stripe"),
        ("cash", "Cash"),
    ]

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=9, decimal_places=2, validators=[MinValueValidator(0)])
    method = models.CharField(max_length=32, choices=METHOD_CHOICES)
    status = models.CharField(max_length=32, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    provider_reference = models.CharField(max_length=128, blank=True)
    provider_response = models.JSONField(blank=True, null=True)
    retry_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="payments_initiated",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment {self.pk} - {self.subscription}"  # pragma: no cover


class Trip(models.Model):
    """Represents a daily trip instance."""

    STATUS_CHOICES = [
        ("scheduled", "Planifié"),
        ("in_progress", "En cours"),
        ("completed", "Terminé"),
        ("cancelled", "Annulé"),
        ("archived", "Archivé"),
    ]

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.SET_NULL,
        related_name="trips",
        null=True,
        blank=True,
    )
    chauffeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trips",
        limit_choices_to={"role": "chauffeur"},
    )
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parent_trips",
        limit_choices_to={"role": "parent"},
    )
    scheduled_date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="scheduled")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    distance_km = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    average_speed_kmh = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    shared_tracking_url = models.URLField(blank=True)
    chauffeur_confirmed_completion_at = models.DateTimeField(null=True, blank=True)
    parent_confirmed_completion_at = models.DateTimeField(null=True, blank=True)
    chauffeur_archived = models.BooleanField(default=False)
    parent_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-scheduled_date", "-started_at"]

    def __str__(self):
        return f"Trajet {self.scheduled_date} - {self.parent}"  # pragma: no cover

    def mark_in_progress(self):
        if not self.started_at:
            self.started_at = timezone.now()
        self.chauffeur_confirmed_completion_at = None
        self.parent_confirmed_completion_at = None
        self.chauffeur_archived = False
        self.parent_archived = False
        self.status = "in_progress"
        self.save(
            update_fields=[
                "status",
                "started_at",
                "chauffeur_confirmed_completion_at",
                "parent_confirmed_completion_at",
                "chauffeur_archived",
                "parent_archived",
            ]
        )

    def mark_completed(self):
        self.status = "completed"
        self.completed_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "completed_at",
                "chauffeur_confirmed_completion_at",
                "parent_confirmed_completion_at",
            ]
        )

    def archive(self, user=None):
        """Archiver une course terminée pour un utilisateur (ou globalement)."""
        if user is None:
            if self.status == "completed":
                self.status = "archived"
                self.save(update_fields=["status"])
                return True
            return False

        if user == self.chauffeur:
            if not self.chauffeur_archived:
                self.chauffeur_archived = True
                self.save(update_fields=["chauffeur_archived"])
            return True
        if user == self.parent:
            if not self.parent_archived:
                self.parent_archived = True
                self.save(update_fields=["parent_archived"])
            return True
        return False

    @property
    def chauffeur_has_confirmed(self) -> bool:
        return self.chauffeur_confirmed_completion_at is not None

    @property
    def parent_has_confirmed(self) -> bool:
        return self.parent_confirmed_completion_at is not None

    @property
    def awaiting_parent_confirmation(self) -> bool:
        return (
            self.chauffeur_has_confirmed
            and not self.parent_has_confirmed
            and self.status == "in_progress"
        )

    @property
    def awaiting_chauffeur_confirmation(self) -> bool:
        return (
            self.parent_has_confirmed
            and not self.chauffeur_has_confirmed
            and self.status == "in_progress"
        )

    def is_archived_for(self, user) -> bool:
        if user == self.chauffeur:
            return self.chauffeur_archived
        if user == self.parent:
            return self.parent_archived
        return False


class Checkpoint(models.Model):
    """GPS checkpoints recorded during a trip."""

    TYPES = [
        ("en_route", "En route"),
        ("arrived", "Arrivé"),
        ("child_picked", "Enfant récupéré"),
        ("child_dropped", "Enfant déposé"),
        ("completed", "Terminé"),
        ("issue", "Incident"),
    ]

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="checkpoints")
    checkpoint_type = models.CharField(max_length=32, choices=TYPES)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["timestamp"]

    def __str__(self):
        return f"{self.checkpoint_type} - {self.trip}"  # pragma: no cover


class RideRequest(models.Model):
    """
    Demandes de course ponctuelles avec critères avancés.
    
    Permet aux particuliers de spécifier des critères précis pour
    leur course et notifie les chauffeurs éligibles en temps réel.
    """

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ride_requests",
        limit_choices_to={"role": "parent"},
    )
    chauffeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assigned_ride_requests",
        limit_choices_to={"role": "chauffeur"},
        null=True,
        blank=True,
        help_text="Chauffeur assigné lors de l'acceptation"
    )
    
    # Informations de base du trajet
    pickup_location = models.CharField("Point de départ", max_length=255)
    dropoff_location = models.CharField("Destination", max_length=255)
    notes = models.TextField("Instructions particulières", blank=True)
    requested_pickup_time = models.DateTimeField("Heure souhaitée", null=True, blank=True)
    
    # Coordonnées GPS pour géolocalisation avancée
    pickup_latitude = models.DecimalField(
        "Latitude départ", 
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True
    )
    pickup_longitude = models.DecimalField(
        "Longitude départ", 
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True
    )
    dropoff_latitude = models.DecimalField(
        "Latitude destination", 
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True
    )
    dropoff_longitude = models.DecimalField(
        "Longitude destination", 
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True
    )
    
    # Critères de sélection du chauffeur
    max_distance_km = models.PositiveIntegerField(
        "Distance maximale (km)", 
        default=10,
        help_text="Rayon de recherche des chauffeurs"
    )
    min_rating = models.DecimalField(
        "Note minimale requise", 
        max_digits=3, 
        decimal_places=1, 
        default=3.0
    )
    
    PRIORITY_CHOICES = [
        ('closest', 'Le plus proche'),
        ('fastest', 'Le plus rapide'),
        ('best_rated', 'Le mieux noté'),
        ('cheapest', 'Le moins cher'),
    ]
    priority = models.CharField(
        "Critère de priorité", 
        max_length=20, 
        choices=PRIORITY_CHOICES, 
        default='closest'
    )
    
    # Options de service
    accept_shared_ride = models.BooleanField("Accepte trajet partagé", default=False)
    need_child_seat = models.BooleanField("Siège enfant requis", default=False)
    
    # Statut et métadonnées
    status = models.CharField(max_length=32, choices=RideRequestStatus.choices, default=RideRequestStatus.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    trip = models.OneToOneField(Trip, on_delete=models.SET_NULL, null=True, blank=True, related_name="ride_request")

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Course {self.parent} -> {self.chauffeur} ({self.status})"  # pragma: no cover

    def accept(self, chauffeur=None):
        """
        Accepte la demande et crée automatiquement le trip de tracking.
        
        Args:
            chauffeur: Chauffeur qui accepte (optionnel si déjà assigné)
            
        Returns:
            Trip: Instance du trip créé pour le tracking
        """
        if self.status != RideRequestStatus.PENDING:
            return self.trip
            
        if chauffeur:
            self.chauffeur = chauffeur
            self.save(update_fields=["chauffeur"])
            
        if not self.chauffeur:
            raise ValueError("Aucun chauffeur assigné pour accepter la demande")
            
        trip = Trip.objects.create(
            subscription=None,
            chauffeur=self.chauffeur,
            parent=self.parent,
            scheduled_date=self.requested_pickup_time.date() if self.requested_pickup_time else timezone.now().date(),
            status="in_progress",
            started_at=timezone.now(),
        )
        self.status = RideRequestStatus.ACCEPTED
        self.trip = trip
        self.responded_at = timezone.now()
        self.save(update_fields=["status", "trip", "responded_at"])
        
        # Marquer le chauffeur comme indisponible
        chauffeur_profile = getattr(self.chauffeur, "chauffeur_profile", None)
        if chauffeur_profile:
            chauffeur_profile.is_available = False
            chauffeur_profile.save(update_fields=["is_available"])
            
        # Démarrer le tracking
        if hasattr(trip, 'mark_in_progress'):
            trip.mark_in_progress()
            
        return trip

    def decline(self, reason: str | None = None):
        if self.status != RideRequestStatus.PENDING:
            return
        self.status = RideRequestStatus.DECLINED
        self.responded_at = timezone.now()
        if reason:
            self.notes = f"{self.notes}\nRefus: {reason}" if self.notes else f"Refus: {reason}"
        self.save(update_fields=["status", "responded_at", "notes"])

    def cancel(self):
        if self.status in {RideRequestStatus.ACCEPTED, RideRequestStatus.COMPLETED}:
            chauffeur_profile = getattr(self.chauffeur, "chauffeur_profile", None)
            if chauffeur_profile:
                chauffeur_profile.is_available = True
                chauffeur_profile.save(update_fields=["is_available"])
        if self.status == RideRequestStatus.PENDING:
            self.status = RideRequestStatus.CANCELLED
            self.responded_at = timezone.now()
            self.save(update_fields=["status", "responded_at"])

    def complete(self):
        if self.trip:
            self.trip.mark_completed()
    
    def get_estimated_distance(self):
        """
        Calcule la distance estimée du trajet si coordonnées disponibles.
        
        Returns:
            float: Distance en km, ou None si pas de coordonnées
        """
        if (self.pickup_latitude and self.pickup_longitude and
            self.dropoff_latitude and self.dropoff_longitude):
            
            from core.utils import calculate_distance
            return calculate_distance(
                float(self.pickup_latitude), float(self.pickup_longitude),
                float(self.dropoff_latitude), float(self.dropoff_longitude)
            )
        return None
    
    def get_eligible_chauffeurs_count(self):
        """
        Retourne le nombre de chauffeurs éligibles selon les critères.
        """
        if self.pickup_latitude and self.pickup_longitude:
            from core.utils import find_available_chauffeurs
            chauffeurs = find_available_chauffeurs(
                pickup_lat=float(self.pickup_latitude),
                pickup_lon=float(self.pickup_longitude),
                max_distance_km=self.max_distance_km,
                min_reliability_score=float(self.min_rating)
            )
            return len(chauffeurs)
        return 0
        self.status = RideRequestStatus.COMPLETED
        self.responded_at = timezone.now()
        self.save(update_fields=["status", "responded_at"])
        chauffeur_profile = getattr(self.chauffeur, "chauffeur_profile", None)
        if chauffeur_profile:
            chauffeur_profile.is_available = True
            chauffeur_profile.save(update_fields=["is_available"])


class Rating(models.Model):
    """Ratings parents give to drivers."""

    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name="rating")
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ratings",
        limit_choices_to={"role": "parent"},
    )
    chauffeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_ratings",
        limit_choices_to={"role": "chauffeur"},
    )
    score = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    badge_suggestion = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Rating {self.score} - {self.chauffeur}"  # pragma: no cover


# === NOUVEAU SYSTÈME D'ABONNEMENTS ===
class SubscriptionType(models.TextChoices):
    """Types d'abonnements disponibles."""
    MOBILITY_PLUS = "mobility_plus", "Mobility Plus"
    CHAUFFEUR = "chauffeur", "Abonnement Chauffeur"


class SubscriptionRequestStatus(models.TextChoices):
    """Statuts des demandes d'abonnement."""
    PENDING = "pending", "En attente"
    ACCEPTED = "accepted", "Acceptée"
    REJECTED = "rejected", "Refusée"
    PAYMENT_PENDING = "payment_pending", "Paiement en attente"
    ACTIVE = "active", "Actif"
    CANCELLED = "cancelled", "Annulé"
    EXPIRED = "expired", "Expiré"


class MobilityPlusSubscription(models.Model):
    """
    Abonnement Mobility Plus - Unique par utilisateur.
    
    Donne accès aux fonctionnalités premium :
    - Chat temps réel
    - GPS avancé
    - Notifications push
    - Support prioritaire
    """
    
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mobility_plus_subscription"
    )
    
    # Informations de base
    start_date = models.DateTimeField(auto_now_add=True)
    next_billing_date = models.DateField()
    price_monthly = models.DecimalField(
        max_digits=8, 
        decimal_places=2,
        default=Decimal('5000.00'),
        help_text="Prix mensuel en FCFA"
    )
    
    # Statut
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=32, choices=SubscriptionStatus.choices, default=SubscriptionStatus.ACTIVE)
    auto_renew = models.BooleanField(default=True)
    
    # Paiement
    last_payment_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=50, blank=True)
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        verbose_name = "Abonnement Mobility Plus"
        verbose_name_plural = "Abonnements Mobility Plus"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Mobility Plus - {self.user.get_full_name()}"
    
    def is_overdue(self):
        """Vérifie si l'abonnement est en retard de paiement."""
        if not self.next_billing_date:
            return False
        return timezone.now().date() > self.next_billing_date
    
    def days_until_billing(self):
        """Nombre de jours jusqu'à la prochaine facturation."""
        if not self.next_billing_date:
            return None
        delta = self.next_billing_date - timezone.now().date()
        return delta.days
    
    def extend_billing_date(self, months=1):
        """Étendre la date de facturation."""
        if self.next_billing_date:
            # Ajouter des mois à la date actuelle
            new_date = self.next_billing_date
            for _ in range(months):
                if new_date.month == 12:
                    new_date = new_date.replace(year=new_date.year + 1, month=1)
                else:
                    new_date = new_date.replace(month=new_date.month + 1)
            self.next_billing_date = new_date
        else:
            self.next_billing_date = timezone.now().date() + timedelta(days=30 * months)
        self.save()
    
    def cancel(self):
        """Annuler l'abonnement."""
        self.is_active = False
        self.auto_renew = False
        self.save()


class ChauffeurSubscriptionRequest(models.Model):
    """
    Demande d'abonnement à un chauffeur spécifique.
    
    Le particulier propose ses conditions et le chauffeur peut accepter/refuser.
    """
    
    # Participants
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chauffeur_subscription_requests",
        limit_choices_to={"role": "parent"}
    )
    chauffeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_subscription_requests",
        limit_choices_to={"role": "chauffeur"}
    )
    
    # Détails de la demande
    title = models.CharField(
        max_length=200,
        help_text="Titre de la demande (ex: Transport scolaire matin/soir)"
    )
    description = models.TextField(
        help_text="Description détaillée des besoins"
    )
    
    # Trajet
    pickup_location = models.CharField(max_length=255)
    dropoff_location = models.CharField(max_length=255)
    pickup_time = models.TimeField(help_text="Heure de départ souhaitée")
    return_time = models.TimeField(null=True, blank=True, help_text="Heure de retour (optionnel)")
    
    # Fréquence
    FREQUENCY_CHOICES = [
        ('daily', 'Quotidien'),
        ('weekdays', 'Jours de semaine'),
        ('weekly', 'Hebdomadaire'),
        ('custom', 'Personnalisé'),
    ]
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='weekdays')
    specific_days = models.JSONField(
        default=list,
        blank=True,
        help_text="Jours spécifiques si fréquence personnalisée (format: [1,2,3,4,5] pour lun-ven)"
    )
    
    # Conditions financières
    proposed_price_monthly = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('10000.00'))],
        help_text="Prix mensuel proposé en FCFA"
    )
    
    # Conditions spéciales
    child_name = models.CharField(max_length=100, blank=True, help_text="Nom de l'enfant (optionnel)")
    special_requirements = models.TextField(
        blank=True,
        help_text="Exigences spéciales (siège enfant, climatisation, etc.)"
    )
    
    # Statut et dates
    status = models.CharField(
        max_length=20,
        choices=SubscriptionRequestStatus.choices,
        default=SubscriptionRequestStatus.PENDING
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(
        help_text="Date d'expiration de la demande"
    )
    
    # Réponse du chauffeur
    chauffeur_response = models.TextField(blank=True)
    chauffeur_counter_offer = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Contre-proposition du chauffeur"
    )
    
    class Meta:
        verbose_name = "Demande d'abonnement chauffeur"
        verbose_name_plural = "Demandes d'abonnement chauffeur"
        ordering = ['-created_at']
        unique_together = ['parent', 'chauffeur', 'status']  # Éviter les doublons actifs
    
    def __str__(self):
        return f"{self.title} - {self.parent.get_full_name()} → {self.chauffeur.get_full_name()}"
    
    def save(self, *args, **kwargs):
        # Définir la date d'expiration si pas définie (7 jours par défaut)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)
    
    def is_expired(self):
        """Vérifie si la demande a expiré."""
        return timezone.now() > self.expires_at
    
    def accept(self, response_message="", counter_offer=None):
        """Accepter la demande d'abonnement."""
        self.status = SubscriptionRequestStatus.PAYMENT_PENDING
        self.responded_at = timezone.now()
        self.chauffeur_response = response_message
        if counter_offer:
            self.chauffeur_counter_offer = counter_offer
        self.save()
        
        # Créer l'abonnement chauffeur en attente de paiement
        return ChauffeurSubscription.objects.create(
            parent=self.parent,
            chauffeur=self.chauffeur,
            subscription_request=self,
            title=self.title,
            pickup_location=self.pickup_location,
            dropoff_location=self.dropoff_location,
            pickup_time=self.pickup_time,
            return_time=self.return_time,
            frequency=self.frequency,
            specific_days=self.specific_days,
            price_monthly=counter_offer or self.proposed_price_monthly,
            child_name=self.child_name,
            special_requirements=self.special_requirements,
            status='payment_pending'
        )
    
    def reject(self, response_message=""):
        """Refuser la demande d'abonnement."""
        self.status = SubscriptionRequestStatus.REJECTED
        self.responded_at = timezone.now()
        self.chauffeur_response = response_message
        self.save()
    
    def get_final_price(self):
        """Obtenir le prix final (contre-offre ou prix proposé)."""
        return self.chauffeur_counter_offer or self.proposed_price_monthly

    def get_status_badge(self):
        return {
            'pending': ('warning', 'En attente'),
            'accepted': ('success', 'Acceptée'),
            'rejected': ('danger', 'Refusée'),
            'payment_pending': ('info', 'Paiement en attente'),
            'active': ('success', 'Actif'),
            'cancelled': ('secondary', 'Annulé'),
            'expired': ('secondary', 'Expiré'),
        }.get(self.status, ('secondary', self.get_status_display()))


class ChauffeurSubscription(models.Model):
    """
    Abonnement actif avec un chauffeur spécifique.
    
    Créé après acceptation d'une demande et paiement validé.
    """
    
    # Référence à la demande originale
    subscription_request = models.OneToOneField(
        ChauffeurSubscriptionRequest,
        on_delete=models.CASCADE,
        related_name="active_subscription"
    )
    
    # Participants
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chauffeur_subscriptions",
        limit_choices_to={"role": "parent"}
    )
    chauffeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parent_subscriptions",
        limit_choices_to={"role": "chauffeur"}
    )
    
    # Informations du service
    title = models.CharField(max_length=200)
    pickup_location = models.CharField(max_length=255)
    dropoff_location = models.CharField(max_length=255)
    pickup_time = models.TimeField()
    return_time = models.TimeField(null=True, blank=True)
    frequency = models.CharField(max_length=20)
    specific_days = models.JSONField(default=list, blank=True)
    
    # Conditions financières
    price_monthly = models.DecimalField(max_digits=9, decimal_places=2)
    
    # Informations personnelles
    child_name = models.CharField(max_length=100, blank=True)
    special_requirements = models.TextField(blank=True)
    
    # Statut et dates
    status = models.CharField(
        max_length=20,
        choices=SubscriptionRequestStatus.choices,
        default=SubscriptionRequestStatus.PAYMENT_PENDING
    )
    
    start_date = models.DateField(null=True, blank=True)
    next_billing_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_payment_date = models.DateField(null=True, blank=True)
    
    # Évaluation
    parent_rating = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    chauffeur_rating = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    
    class Meta:
        verbose_name = "Abonnement chauffeur"
        verbose_name_plural = "Abonnements chauffeur"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.parent.get_full_name()} ↔ {self.chauffeur.get_full_name()}"
    
    def activate_after_payment(self):
        """Activer l'abonnement après paiement validé."""
        self.status = SubscriptionRequestStatus.ACTIVE
        self.start_date = timezone.now().date()
        self.next_billing_date = timezone.now().date() + timedelta(days=30)
        self.save()
        
        # Mettre à jour la demande originale
        if self.subscription_request:
            self.subscription_request.status = SubscriptionRequestStatus.ACTIVE
            self.subscription_request.save()
    
    def cancel(self, cancelled_by=None):
        """Annuler l'abonnement."""
        self.status = SubscriptionRequestStatus.CANCELLED
        self.end_date = timezone.now().date()
        self.save()
        
        if self.subscription_request:
            self.subscription_request.status = SubscriptionRequestStatus.CANCELLED
            self.subscription_request.save()
    
    def is_overdue(self):
        """Vérifier si l'abonnement est en retard de paiement."""
        if not self.next_billing_date:
            return False
        return timezone.now().date() > self.next_billing_date
    
    def extend_billing_date(self, months=1):
        """Étendre la date de facturation."""
        if self.next_billing_date:
            new_date = self.next_billing_date
            for _ in range(months):
                if new_date.month == 12:
                    new_date = new_date.replace(year=new_date.year + 1, month=1)
                else:
                    new_date = new_date.replace(month=new_date.month + 1)
            self.next_billing_date = new_date
        else:
            self.next_billing_date = timezone.now().date() + timedelta(days=30 * months)
        self.save()


class SubscriptionPayment(models.Model):
    """
    Paiements pour tous types d'abonnements.
    
    Unifie les paiements Mobility Plus et abonnements chauffeur.
    """
    
    PAYMENT_TYPE_CHOICES = [
        ('mobility_plus', 'Mobility Plus'),
        ('chauffeur_subscription', 'Abonnement Chauffeur'),
    ]
    
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('processing', 'En cours'),
        ('completed', 'Terminé'),
        ('failed', 'Échoué'),
        ('refunded', 'Remboursé'),
    ]
    
    # Type de paiement
    payment_type = models.CharField(max_length=30, choices=PAYMENT_TYPE_CHOICES)
    
    # Références aux abonnements
    mobility_plus_subscription = models.ForeignKey(
        MobilityPlusSubscription,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payments"
    )
    chauffeur_subscription = models.ForeignKey(
        ChauffeurSubscription,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payments"
    )
    
    # Utilisateur payeur
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscription_payments"
    )
    
    # Informations de paiement
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='XAF')  # Franc CFA
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    
    # Méthode de paiement
    payment_method = models.CharField(max_length=50)  # 'mobile_money', 'stripe', etc.
    transaction_id = models.CharField(max_length=255, blank=True)
    external_reference = models.CharField(max_length=255, blank=True)
    
    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    
    # Métadonnées
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        verbose_name = "Paiement d'abonnement"
        verbose_name_plural = "Paiements d'abonnements"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Paiement {self.amount} XAF - {self.user.get_full_name()} ({self.get_payment_type_display()})"
    
    def mark_as_paid(self):
        """Marquer le paiement comme payé et activer l'abonnement."""
        self.status = 'completed'
        self.paid_at = timezone.now()
        self.save()
        
        # Activer l'abonnement correspondant
        if self.mobility_plus_subscription:
            self.mobility_plus_subscription.is_active = True
            self.mobility_plus_subscription.last_payment_date = timezone.now().date()
            self.mobility_plus_subscription.save()
            
        elif self.chauffeur_subscription:
            self.chauffeur_subscription.activate_after_payment()
    
    def mark_as_failed(self, reason=""):
        """Marquer le paiement comme échoué."""
        self.status = 'failed'
        self.description = reason
        self.save()
    
    def get_subscription(self):
        """Obtenir l'abonnement associé."""
        if self.mobility_plus_subscription:
            return self.mobility_plus_subscription
        elif self.chauffeur_subscription:
            return self.chauffeur_subscription
        return None


class ChatMessage(models.Model):
    """Modèle pour les messages de chat."""
    
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_messages'
    )
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Message de chat"
        verbose_name_plural = "Messages de chat"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.sender.get_full_name()} → {self.recipient.get_full_name()}: {self.message[:50]}..."
    
    @property
    def sender_has_mobility_plus(self):
        """Vérifier si l'expéditeur a Mobility Plus."""
        try:
            return (self.sender.mobility_plus_subscription.is_active and 
                   self.sender.mobility_plus_subscription.status == 'active')
        except:
            return False
    
    @property
    def recipient_has_mobility_plus(self):
        """Vérifier si le destinataire a Mobility Plus."""
        try:
            return (self.recipient.mobility_plus_subscription.is_active and 
                   self.recipient.mobility_plus_subscription.status == 'active')
        except:
            return False
