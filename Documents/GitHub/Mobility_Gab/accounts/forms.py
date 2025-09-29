"""Forms for account-related operations."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from .models import ChauffeurProfile, ParentProfile, Profile, UserRoles


User = get_user_model()


ROLE_CHOICES = (
    (UserRoles.PARENT, "Particulier"),
    (UserRoles.CHAUFFEUR, "Chauffeur"),
)


class BaseRegistrationForm(forms.Form):
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.HiddenInput())
    username = forms.CharField(max_length=150, label="Nom d'utilisateur")
    first_name = forms.CharField(max_length=150, label="Prénom")
    last_name = forms.CharField(max_length=150, label="Nom")
    email = forms.EmailField(label="Adresse email")
    phone = forms.CharField(label="Numéro de téléphone")
    address = forms.CharField(label="Adresse")
    password1 = forms.CharField(widget=forms.PasswordInput, label="Mot de passe")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirmer le mot de passe")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if hasattr(field.widget, "attrs"):
                field.widget.attrs.setdefault("class", "form-control")
        # hidden role should not inherit input styling
        self.fields["role"].widget.attrs.pop("class", None)
        self.show_vehicle_hint = False

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec cet email.")
        return email

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ce nom d'utilisateur est déjà utilisé.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Les mots de passe ne correspondent pas.")
        return cleaned_data

    def save(self):
        raise NotImplementedError


class ParentRegistrationForm(BaseRegistrationForm):
    role = forms.CharField(initial=UserRoles.PARENT, widget=forms.HiddenInput())

    def save(self):
        data = self.cleaned_data
        user = User.objects.create_user(
            username=data["username"],
            email=data["email"],
            password=data["password1"],
            role=UserRoles.PARENT,
            first_name=data["first_name"],
            last_name=data["last_name"],
        )
        profile = user.profile
        profile.phone = data["phone"]
        profile.address = data["address"]
        profile.save(update_fields=["phone", "address"])
        return user


class ChauffeurRegistrationForm(BaseRegistrationForm):
    role = forms.CharField(initial=UserRoles.CHAUFFEUR, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle_placeholder"] = forms.CharField(
            label="Informations véhicule",
            required=False,
            help_text="À renseigner plus tard dans votre espace chauffeur.",
            widget=forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Marque, modèle, immatriculation...",
                    "disabled": True,
                }
            ),
        )
        self.show_vehicle_hint = True

    def save(self):
        data = self.cleaned_data
        user = User.objects.create_user(
            username=data["username"],
            email=data["email"],
            password=data["password1"],
            role=UserRoles.CHAUFFEUR,
            first_name=data["first_name"],
            last_name=data["last_name"],
        )
        profile = user.profile
        profile.phone = data["phone"]
        profile.address = data["address"]
        profile.save(update_fields=["phone", "address"])
        return user


class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Nom d'utilisateur")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def confirm_login_allowed(self, user):
        if user.is_suspended:
            raise forms.ValidationError(
                "Votre compte est suspendu. Veuillez régulariser votre paiement ou contacter le support.",
                code="inactive",
            )


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom d'utilisateur"}),
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Prénom"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Adresse email"}),
        }
        labels = {
            "username": "Nom d'utilisateur",
            "first_name": "Prénom",
            "last_name": "Nom",
            "email": "Adresse email",
        }


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["phone", "address", "photo", "bio", "push_notifications_enabled", "sms_notifications_enabled"]
        widgets = {
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Numéro de téléphone"}),
            "address": forms.TextInput(attrs={"class": "form-control", "placeholder": "Adresse"}),
            "photo": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "bio": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "À propos de moi"}),
            "push_notifications_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "sms_notifications_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "phone": "Téléphone",
            "address": "Adresse",
            "photo": "Photo de profil",
            "bio": "Biographie",
            "push_notifications_enabled": "Activer les notifications push",
            "sms_notifications_enabled": "Activer les notifications SMS",
        }


class ParentProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = ParentProfile
        fields = ["emergency_contact_name", "emergency_contact_phone", "home_address", "work_address"]
        widgets = {
            "emergency_contact_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom du contact d'urgence"}),
            "emergency_contact_phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Téléphone du contact d'urgence"}),
            "home_address": forms.TextInput(attrs={"class": "form-control", "placeholder": "Adresse domicile"}),
            "work_address": forms.TextInput(attrs={"class": "form-control", "placeholder": "Adresse travail"}),
        }
        labels = {
            "emergency_contact_name": "Nom du contact d'urgence",
            "emergency_contact_phone": "Téléphone du contact d'urgence",
            "home_address": "Adresse domicile",
            "work_address": "Adresse travail",
        }


class ChauffeurProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = ChauffeurProfile
        fields = [
            "driving_license_number",
            "license_expiry",
            "vehicle_make",
            "vehicle_model",
            "vehicle_color",
            "vehicle_plate",
            "zone",
            "current_latitude",
            "current_longitude",
            "is_available",
        ]
        widgets = {
            "driving_license_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Numéro de permis"}),
            "license_expiry": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "vehicle_make": forms.TextInput(attrs={"class": "form-control", "placeholder": "Marque"}),
            "vehicle_model": forms.TextInput(attrs={"class": "form-control", "placeholder": "Modèle"}),
            "vehicle_color": forms.TextInput(attrs={"class": "form-control", "placeholder": "Couleur"}),
            "vehicle_plate": forms.TextInput(attrs={"class": "form-control", "placeholder": "Immatriculation"}),
            "zone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Zone de service"}),
            "current_latitude": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001"}),
            "current_longitude": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001"}),
            "is_available": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "driving_license_number": "Numéro de permis",
            "license_expiry": "Expiration du permis",
            "vehicle_make": "Marque du véhicule",
            "vehicle_model": "Modèle du véhicule",
            "vehicle_color": "Couleur du véhicule",
            "vehicle_plate": "Immatriculation",
            "zone": "Zone d'activité",
            "current_latitude": "Latitude actuelle",
            "current_longitude": "Longitude actuelle",
            "is_available": "Disponible pour une course",
        }


class PasswordUpdateForm(forms.Form):
    current_password = forms.CharField(
        label="Mot de passe actuel",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Mot de passe actuel"}),
        required=False,
    )
    new_password = forms.CharField(
        label="Nouveau mot de passe",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Nouveau mot de passe"}),
        required=False,
    )
    confirm_password = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Confirmer le mot de passe"}),
        required=False,
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")
        current_password = cleaned_data.get("current_password")
        if any([current_password, new_password, confirm_password]):
            if not current_password:
                self.add_error("current_password", "Merci de saisir votre mot de passe actuel.")
            elif not self.user.check_password(current_password):
                self.add_error("current_password", "Mot de passe actuel incorrect.")
            if not new_password:
                self.add_error("new_password", "Merci de saisir un nouveau mot de passe.")
            if new_password and confirm_password and new_password != confirm_password:
                self.add_error("confirm_password", "Les mots de passe ne correspondent pas.")
        return cleaned_data

    def should_change_password(self):
        return bool(
            self.cleaned_data.get("new_password")
            and self.cleaned_data.get("confirm_password")
            and self.cleaned_data.get("current_password")
        )

