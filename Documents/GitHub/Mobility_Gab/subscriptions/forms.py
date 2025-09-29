"""
Formulaires pour les demandes de course et abonnements.

Ce fichier contient tous les formulaires liés aux demandes de course
avec géolocalisation, critères de sélection, et préférences utilisateur.
"""

from django import forms
from django.utils import timezone
from decimal import Decimal
from accounts.models import User, UserRoles


class RideRequestForm(forms.Form):
    """
    Formulaire pour créer une demande de course avec critères avancés.
    
    Permet aux particuliers de spécifier :
    - Départ et destination avec géolocalisation
    - Critères de sélection du chauffeur
    - Préférences de service
    """
    
    # Informations de base du trajet
    pickup_location = forms.CharField(
        label="Point de départ",
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "form-control", 
            "placeholder": "Ex: Bastos, Yaoundé",
            "id": "pickup-input"
        }),
        help_text="Cliquez sur 'Localiser' pour utiliser votre position actuelle"
    )
    
    dropoff_location = forms.CharField(
        label="Destination",
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "form-control", 
            "placeholder": "Ex: Melen, Yaoundé",
            "id": "dropoff-input"
        }),
    )
    
    # Coordonnées GPS (remplies automatiquement)
    pickup_latitude = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9, 
        decimal_places=6
    )
    pickup_longitude = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9, 
        decimal_places=6
    )
    dropoff_latitude = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9, 
        decimal_places=6
    )
    dropoff_longitude = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9, 
        decimal_places=6
    )
    
    # Timing
    requested_pickup_time = forms.DateTimeField(
        label="Heure souhaitée",
        widget=forms.DateTimeInput(
            attrs={
                "class": "form-control", 
                "type": "datetime-local"
            },
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
        help_text="Minimum 10 minutes à l'avance"
    )
    
    # Critères de sélection du chauffeur
    max_distance_km = forms.IntegerField(
        label="Distance maximale du chauffeur (km)",
        initial=10,
        min_value=1,
        max_value=50,
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "min": "1",
            "max": "50"
        }),
        help_text="Rayon de recherche des chauffeurs disponibles"
    )
    
    min_rating = forms.DecimalField(
        label="Note minimale du chauffeur",
        initial=3.0,
        min_value=1.0,
        max_value=5.0,
        decimal_places=1,
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "min": "1.0",
            "max": "5.0",
            "step": "0.5"
        }),
        help_text="Note minimale acceptée (sur 5)"
    )
    
    # Préférences de service
    PRIORITY_CHOICES = [
        ('closest', 'Le plus proche'),
        ('fastest', 'Le plus rapide'),
        ('best_rated', 'Le mieux noté'),
        ('cheapest', 'Le moins cher'),
    ]
    
    priority = forms.ChoiceField(
        label="Priorité de sélection",
        choices=PRIORITY_CHOICES,
        initial='closest',
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Critère principal pour choisir le chauffeur"
    )
    
    # Options supplémentaires
    accept_shared_ride = forms.BooleanField(
        label="Accepter un trajet partagé",
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Réduction possible si d'autres passagers"
    )
    
    need_child_seat = forms.BooleanField(
        label="Siège enfant requis",
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Pour enfants de moins de 10 ans"
    )
    
    # Communication
    notes = forms.CharField(
        label="Instructions particulières",
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control", 
            "placeholder": "Détails sur le point de rendez-vous, instructions spéciales...",
            "rows": 3
        }),
        help_text="Informations utiles pour le chauffeur"
    )
    
    # Chauffeur suggéré (optionnel)
    suggested_chauffeur = forms.ModelChoiceField(
        label="Chauffeur préféré (optionnel)",
        queryset=User.objects.filter(role=UserRoles.CHAUFFEUR, is_active=True),
        required=False,
        empty_label="Aucune préférence",
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Si disponible, ce chauffeur sera prioritaire"
    )
    
    def __init__(self, *args, **kwargs):
        """Initialise le formulaire avec les chauffeurs disponibles."""
        super().__init__(*args, **kwargs)
        
        # Mettre à jour la queryset des chauffeurs disponibles
        self.fields['suggested_chauffeur'].queryset = User.objects.filter(
            role=UserRoles.CHAUFFEUR,
            is_active=True,
            chauffeur_profile__is_available=True
        ).select_related('chauffeur_profile')
        
        # Valeur par défaut pour l'heure
        if not self.initial.get('requested_pickup_time'):
            self.initial['requested_pickup_time'] = timezone.now() + timezone.timedelta(minutes=15)
    
    def clean_requested_pickup_time(self):
        """Valide que l'heure de pickup est dans le futur."""
        pickup_time = self.cleaned_data['requested_pickup_time']
        
        if pickup_time <= timezone.now() + timezone.timedelta(minutes=10):
            raise forms.ValidationError(
                "L'heure de prise en charge doit être au moins 10 minutes dans le futur."
            )
        
        # Pas plus de 7 jours à l'avance
        if pickup_time > timezone.now() + timezone.timedelta(days=7):
            raise forms.ValidationError(
                "Impossible de programmer une course plus de 7 jours à l'avance."
            )
        
        return pickup_time
    
    def clean(self):
        """Validation croisée des champs."""
        cleaned_data = super().clean()
        
        pickup_location = cleaned_data.get('pickup_location')
        dropoff_location = cleaned_data.get('dropoff_location')
        
        # Vérifier que départ et destination sont différents
        if pickup_location and dropoff_location:
            if pickup_location.lower().strip() == dropoff_location.lower().strip():
                raise forms.ValidationError(
                    "Le point de départ et la destination doivent être différents."
                )
        
        return cleaned_data


class RideRequestFilterForm(forms.Form):
    status = forms.ChoiceField(
        label="Statut",
        required=False,
        choices=[("", "Tous les statuts"), ("pending", "En attente"), ("accepted", "Acceptées"), ("declined", "Refusées"), ("completed", "Terminées")],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-select")


class ChauffeurSubscriptionRequestForm(forms.Form):
    """
    Formulaire pour demander un abonnement à un chauffeur spécifique.
    
    Le particulier propose ses conditions et le chauffeur peut accepter/refuser.
    """
    
    # Sélection du chauffeur
    chauffeur = forms.ModelChoiceField(
        label="Chauffeur souhaité",
        queryset=User.objects.filter(role=UserRoles.CHAUFFEUR, is_active=True),
        empty_label="Sélectionnez un chauffeur",
        widget=forms.Select(attrs={"class": "form-select", "id": "chauffeur-select"}),
        help_text="Choisissez le chauffeur avec qui vous souhaitez vous abonner"
    )
    
    # Informations de base
    title = forms.CharField(
        label="Titre de la demande",
        max_length=200,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ex: Transport scolaire matin/soir"
        }),
        help_text="Donnez un titre descriptif à votre demande"
    )
    
    description = forms.CharField(
        label="Description détaillée",
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "placeholder": "Décrivez vos besoins spécifiques...",
            "rows": 4
        }),
        help_text="Expliquez en détail ce que vous attendez de cet abonnement"
    )
    
    # Trajet
    pickup_location = forms.CharField(
        label="Point de départ",
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ex: Bastos, Yaoundé"
        })
    )
    
    dropoff_location = forms.CharField(
        label="Destination",
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ex: Melen, Yaoundé"
        })
    )
    
    # Horaires
    pickup_time = forms.TimeField(
        label="Heure de départ",
        widget=forms.TimeInput(attrs={
            "class": "form-control",
            "type": "time"
        }),
        help_text="Heure à laquelle vous souhaitez être pris en charge"
    )
    
    return_time = forms.TimeField(
        label="Heure de retour (optionnel)",
        required=False,
        widget=forms.TimeInput(attrs={
            "class": "form-control",
            "type": "time"
        }),
        help_text="Si vous avez besoin d'un retour"
    )
    
    # Fréquence
    FREQUENCY_CHOICES = [
        ('daily', 'Quotidien'),
        ('weekdays', 'Jours de semaine (lun-ven)'),
        ('weekly', 'Hebdomadaire'),
        ('custom', 'Personnalisé'),
    ]
    
    frequency = forms.ChoiceField(
        label="Fréquence",
        choices=FREQUENCY_CHOICES,
        initial='weekdays',
        widget=forms.Select(attrs={"class": "form-select"})
    )
    
    # Conditions financières
    proposed_price_monthly = forms.DecimalField(
        label="Prix mensuel proposé (FCFA)",
        max_digits=9,
        decimal_places=2,
        min_value=Decimal('10000.00'),
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "min": "10000",
            "step": "1000"
        }),
        help_text="Prix que vous proposez pour cet abonnement mensuel"
    )
    
    # Informations personnelles
    child_name = forms.CharField(
        label="Nom de l'enfant (optionnel)",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Nom de l'enfant qui sera transporté"
        })
    )
    
    special_requirements = forms.CharField(
        label="Exigences spéciales",
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "placeholder": "Siège enfant, climatisation, musique, etc.",
            "rows": 3
        }),
        help_text="Décrivez vos besoins particuliers"
    )
    
    def __init__(self, *args, **kwargs):
        """Initialise le formulaire avec les chauffeurs disponibles."""
        super().__init__(*args, **kwargs)
        
        # Mettre à jour la queryset des chauffeurs disponibles
        self.fields['chauffeur'].queryset = User.objects.filter(
            role=UserRoles.CHAUFFEUR,
            is_active=True
        ).select_related('chauffeur_profile')
    
    def clean(self):
        """Validation croisée des champs."""
        cleaned_data = super().clean()
        
        pickup_location = cleaned_data.get('pickup_location')
        dropoff_location = cleaned_data.get('dropoff_location')
        
        # Vérifier que départ et destination sont différents
        if pickup_location and dropoff_location:
            if pickup_location.lower().strip() == dropoff_location.lower().strip():
                raise forms.ValidationError(
                    "Le point de départ et la destination doivent être différents."
                )
        
        return cleaned_data


class ChauffeurResponseForm(forms.Form):
    """
    Formulaire pour que le chauffeur réponde à une demande d'abonnement.
    """
    
    ACTION_CHOICES = [
        ('accept', 'Accepter'),
        ('reject', 'Refuser'),
    ]
    
    action = forms.ChoiceField(
        label="Action",
        choices=ACTION_CHOICES,
        widget=forms.RadioSelect(attrs={"class": "form-check-input"})
    )
    
    response_message = forms.CharField(
        label="Message de réponse",
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "placeholder": "Message pour le particulier...",
            "rows": 3
        }),
        help_text="Message optionnel à envoyer au particulier"
    )
    
    counter_offer = forms.DecimalField(
        label="Contre-proposition (FCFA)",
        required=False,
        max_digits=9,
        decimal_places=2,
        min_value=Decimal('10000.00'),
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "min": "10000",
            "step": "1000"
        }),
        help_text="Prix que vous proposez (optionnel)"
    )
