"""Signals for accounts app."""

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ChauffeurProfile, ParentProfile, Profile, UserRoles


@receiver(post_save, sender=get_user_model())
def create_user_profiles(sender, instance, created, **kwargs):
    """Automatically create profile objects when user is created."""

    if created:
        Profile.objects.create(user=instance)

    if instance.role == UserRoles.PARENT and not hasattr(instance, "parent_profile"):
        ParentProfile.objects.create(user=instance)
    elif instance.role == UserRoles.CHAUFFEUR and not hasattr(instance, "chauffeur_profile"):
        ChauffeurProfile.objects.create(user=instance)

