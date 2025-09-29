"""API viewsets for accounts."""

from django.contrib.auth import get_user_model
from django.db.models import Avg
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView as SimpleJWTObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView as SimpleJWTRefreshView

from .models import ChauffeurProfile, ParentProfile, Profile, UserRoles
from .serializers import (
    ChauffeurProfileSerializer,
    PasswordChangeSerializer,
    ParentProfileSerializer,
    ProfileSerializer,
    RegistrationSerializer,
    UserSerializer,
)

User = get_user_model()


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ("role", "is_active", "is_suspended")
    search_fields = ("email", "first_name", "last_name")

    def get_permissions(self):
        if self.action in {"create"}:
            return [permissions.AllowAny()]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        headers = self.get_success_headers(serializer.data)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def change_password(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Mot de passe mis à jour"})


class ProfileViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = Profile.objects.select_related("user")
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role == UserRoles.ADMIN:
            return self.queryset
        return self.queryset.filter(user=self.request.user)


class ParentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ParentProfile.objects.select_related("user")
    serializer_class = ParentProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ("user__is_suspended",)
    search_fields = ("user__email", "emergency_contact_name")

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == UserRoles.CHAUFFEUR:
            return qs.filter(user__assigned_subscriptions__chauffeur=user).distinct()
        if user.role != UserRoles.ADMIN:
            return qs.filter(user=user)
        return qs


class ChauffeurViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ChauffeurProfile.objects.select_related("user")
    serializer_class = ChauffeurProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ("zone",)
    search_fields = ("user__email", "vehicle_plate", "zone")
    ordering_fields = ("reliability_score",)

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == UserRoles.PARENT:
            return qs.filter(user__subscriptions__parent=user).distinct()
        return qs

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated])
    def leaderboard(self, request):
        top_chauffeurs = (
            self.get_queryset()
            .annotate(avg_rating=Avg("user__received_ratings__score"))
            .order_by("-avg_rating")[:10]
        )
        serializer = self.get_serializer(top_chauffeurs, many=True)
        return Response(serializer.data)


class TokenObtainPairView(SimpleJWTObtainPairView):
    pass


class TokenRefreshView(SimpleJWTRefreshView):
    pass

