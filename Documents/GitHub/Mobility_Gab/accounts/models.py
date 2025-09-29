"""
Modèles de données pour l'application Accounts (Comptes utilisateurs).

Ce fichier définit les modèles principaux pour la gestion des utilisateurs :
- User : Utilisateur personnalisé avec rôles (Particulier, Chauffeur, Admin)
- Profile : Profil générique pour tous les utilisateurs
- ParentProfile : Profil spécifique aux particuliers
- ChauffeurProfile : Profil spécifique aux chauffeurs
"""

from datetime import date

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import BaseUserManager
from django.core.validators import RegexValidator
from django.db import models


class UserRoles(models.TextChoices):
    """
    Énumération des rôles utilisateur disponibles dans l'application.
    
    - PARENT : Particulier qui demande des courses
    - CHAUFFEUR : Conducteur qui effectue les courses
    - ADMIN : Administrateur avec accès complet
    """
    PARENT = "parent", "Particulier"
    CHAUFFEUR = "chauffeur", "Chauffeur"
    ADMIN = "admin", "Admin"


class UserManager(BaseUserManager):
    """
    Gestionnaire personnalisé pour le modèle User.
    
    Permet de créer des utilisateurs avec email et username,
    et gère la création des superutilisateurs.
    """

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """
        Méthode privée pour créer un utilisateur.
        
        Args:
            email: Adresse email de l'utilisateur
            password: Mot de passe
            **extra_fields: Champs supplémentaires
            
        Returns:
            User: Instance de l'utilisateur créé
        """
        if not email:
            raise ValueError("Le champ email doit être renseigné")
        email = self.normalize_email(email)
        # Génère un username à partir de l'email si non fourni
        username = extra_fields.pop("username", None) or email.split("@")[0]
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """
        Crée un utilisateur standard (non-staff, non-superuser).
        """
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """
        Crée un superutilisateur avec tous les privilèges.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRoles.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un super utilisateur doit avoir is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un super utilisateur doit avoir is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Modèle utilisateur personnalisé étendant AbstractUser de Django.
    
    Ajoute des fonctionnalités spécifiques à Mobility Gab :
    - Système de rôles (Particulier, Chauffeur, Admin)
    - Vérification d'email
    - Système de suspension
    """

    # Email unique pour chaque utilisateur
    email = models.EmailField(unique=True)
    
    # Rôle de l'utilisateur (voir UserRoles)
    role = models.CharField(max_length=32, choices=UserRoles.choices, default=UserRoles.PARENT)
    
    # Vérification d'email (pour futures fonctionnalités)
    is_email_verified = models.BooleanField(default=False)
    
    # Système de suspension
    suspended_until = models.DateField(null=True, blank=True)
    is_suspended = models.BooleanField(default=False)
    suspended_reason = models.CharField(max_length=255, blank=True)

    # Configuration Django : utilise username pour la connexion
    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    objects = UserManager()

    def __str__(self):
        """Représentation textuelle de l'utilisateur."""
        return f"{self.get_full_name()} ({self.username})"

    def lift_suspension(self):
        """
        Lève la suspension d'un utilisateur.
        Remet à zéro tous les champs liés à la suspension.
        """
        self.is_suspended = False
        self.suspended_until = None
        self.suspended_reason = ""
        self.save(update_fields=["is_suspended", "suspended_until", "suspended_reason"])

    def suspend(self, reason: str, until: date | None = None):
        """
        Suspend un utilisateur avec une raison et optionnellement une date de fin.
        
        Args:
            reason: Raison de la suspension
            until: Date de fin de suspension (optionnelle)
        """
        self.is_suspended = True
        self.suspended_reason = reason
        self.suspended_until = until
        self.save(update_fields=["is_suspended", "suspended_until", "suspended_reason"])


class Profile(models.Model):
    """
    Profil générique pour tous les utilisateurs.
    
    Contient les informations de base communes à tous les types d'utilisateurs :
    - Informations de contact (téléphone, adresse)
    - Photo de profil
    - Préférences de notifications
    """

    # Relation OneToOne avec User - chaque utilisateur a un profil unique
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    
    # Validation du numéro de téléphone avec regex
    phone_regex = RegexValidator(regex=r"^\+?[0-9]{9,15}$", message="Numéro de téléphone invalide")
    phone = models.CharField(validators=[phone_regex], max_length=17, blank=True)
    
    # Photo de profil stockée dans media/profiles/photos/
    photo = models.ImageField(upload_to="profiles/photos/", blank=True, null=True)
    
    # Biographie/description personnelle
    bio = models.TextField(blank=True)
    
    # Adresse principale
    address = models.CharField(max_length=255, blank=True)
    
    # Préférences de notifications
    push_notifications_enabled = models.BooleanField(default=True)
    sms_notifications_enabled = models.BooleanField(default=False)

    def __str__(self):
        """Représentation textuelle du profil."""
        return f"Profil {self.user}"


class ParentProfile(models.Model):
    """
    Profil spécifique aux particuliers/parents.
    
    Contient les informations spécifiques aux utilisateurs qui demandent des courses :
    - Contacts d'urgence
    - Adresses fréquentes (domicile, travail)
    """

    # Relation OneToOne avec User
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="parent_profile")
    
    # Contact d'urgence (obligatoire pour la sécurité)
    emergency_contact_name = models.CharField(max_length=128, blank=True)
    emergency_contact_phone = models.CharField(max_length=17, blank=True)
    
    # Adresses fréquentes pour faciliter les demandes de course
    home_address = models.CharField(max_length=255, blank=True)
    work_address = models.CharField(max_length=255, blank=True)

    def __str__(self):
        """Représentation textuelle du profil particulier."""
        return f"ParentProfile {self.user}"


class ChauffeurProfile(models.Model):
    """
    Profil spécifique aux chauffeurs.
    
    Contient toutes les informations nécessaires pour les conducteurs :
    - Informations légales (permis de conduire)
    - Informations véhicule
    - Géolocalisation et disponibilité
    - Système de notation et badges
    """

    # Relation OneToOne avec User
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="chauffeur_profile")
    
    # Informations légales du conducteur
    driving_license_number = models.CharField("Numéro de permis", max_length=64, blank=True)
    license_expiry = models.DateField("Expiration du permis", null=True, blank=True)
    
    # Informations du véhicule
    vehicle_make = models.CharField("Marque du véhicule", max_length=64, blank=True)
    vehicle_model = models.CharField("Modèle du véhicule", max_length=64, blank=True)
    vehicle_color = models.CharField("Couleur du véhicule", max_length=32, blank=True)
    vehicle_plate = models.CharField("Immatriculation", max_length=32, blank=True)
    
    # Zone d'activité géographique
    zone = models.CharField("Zone d'activité", max_length=64, blank=True)
    
    # Système de notation (score sur 5, calculé à partir des avis)
    reliability_score = models.DecimalField("Score de fiabilité", max_digits=4, decimal_places=2, default=5.00)
    total_ratings = models.PositiveIntegerField("Nombre d'avis", default=0)
    
    # Position GPS actuelle pour le matching géographique
    current_latitude = models.DecimalField("Latitude actuelle", max_digits=9, decimal_places=6, null=True, blank=True)
    current_longitude = models.DecimalField("Longitude actuelle", max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Disponibilité pour accepter de nouvelles courses
    is_available = models.BooleanField("Disponible pour une course", default=True)
    
    # Système de badges/récompenses (relation ManyToMany via table intermédiaire)
    active_badges = models.ManyToManyField(
        "core.Badge",
        through="ChauffeurBadge",
        blank=True,
        related_name="chauffeurs",
    )

    def __str__(self):
        """Représentation textuelle du profil chauffeur."""
        return f"Chauffeur {self.user}"


class ChauffeurBadge(models.Model):
    """
    Table de liaison entre chauffeurs et badges.
    
    Permet de suivre quand et par qui un badge a été attribué,
    avec des notes optionnelles sur la raison de l'attribution.
    """

    # Relations vers le chauffeur et le badge
    chauffeur = models.ForeignKey(ChauffeurProfile, on_delete=models.CASCADE)
    badge = models.ForeignKey("core.Badge", on_delete=models.CASCADE)
    
    # Métadonnées de l'attribution
    awarded_at = models.DateTimeField(auto_now_add=True)
    awarded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="badges_awarded")
    notes = models.TextField(blank=True)

    class Meta:
        # Un chauffeur ne peut avoir le même badge qu'une fois
        unique_together = ("chauffeur", "badge")

    def __str__(self):
        """Représentation textuelle de l'attribution de badge."""
        return f"{self.badge} -> {self.chauffeur}"
