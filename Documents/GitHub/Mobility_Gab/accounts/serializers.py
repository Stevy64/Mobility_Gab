"""Serializers for account models."""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import ChauffeurBadge, ChauffeurProfile, ParentProfile, Profile, UserRoles

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "is_suspended",
            "is_email_verified",
            "suspended_reason",
            "suspended_until",
            "date_joined",
        )


class RegistrationSerializer(serializers.ModelSerializer):
    password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ("username", "email", "role", "first_name", "last_name", "password1", "password2")

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Cet email est déjà utilisé.")
        return value

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Ce nom d'utilisateur est déjà utilisé.")
        return value

    def validate_role(self, value):
        if value not in [UserRoles.PARENT, UserRoles.CHAUFFEUR]:
            raise serializers.ValidationError("Choix de rôle invalide.")
        return value

    def validate(self, attrs):
        if attrs["password1"] != attrs["password2"]:
            raise serializers.ValidationError("Les mots de passe ne correspondent pas.")
        validate_password(attrs["password1"])
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password1")
        validated_data.pop("password2")
        return User.objects.create_user(password=password, **validated_data)


class ProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Profile
        fields = (
            "id",
            "user",
            "phone",
            "address",
            "photo",
            "bio",
            "push_notifications_enabled",
            "sms_notifications_enabled",
        )


class ParentProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = ParentProfile
        fields = (
            "id",
            "user",
            "emergency_contact_name",
            "emergency_contact_phone",
            "home_address",
            "work_address",
        )


class ChauffeurBadgeSerializer(serializers.ModelSerializer):
    badge_name = serializers.ReadOnlyField(source="badge.name")
    badge_icon = serializers.ReadOnlyField(source="badge.icon")

    class Meta:
        model = ChauffeurBadge
        fields = ("id", "badge", "badge_name", "badge_icon", "awarded_at", "awarded_by", "notes")


class ChauffeurProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    badges = ChauffeurBadgeSerializer(source="chauffeurbadge_set", many=True, read_only=True)

    class Meta:
        model = ChauffeurProfile
        fields = (
            "id",
            "user",
            "driving_license_number",
            "license_expiry",
            "vehicle_make",
            "vehicle_model",
            "vehicle_color",
            "vehicle_plate",
            "zone",
            "reliability_score",
            "total_ratings",
            "badges",
        )


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Ancien mot de passe incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value)
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user

