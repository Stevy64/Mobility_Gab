"""API viewsets for subscriptions and operations."""

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRoles
from core.models import NotificationLog, SOSAlert
from .models import (
    Checkpoint,
    Payment,
    Rating,
    RideRequest,
    RideRequestStatus,
    Subscription,
    SubscriptionPlan,
    Trip,
)
from .serializers import (
    CheckpointSerializer,
    MobileMoneyWebhookSerializer,
    NotificationSerializer,
    PaymentSerializer,
    RatingSerializer,
    RideRequestSerializer,
    SOSAlertSerializer,
    StripeWebhookSerializer,
    SubscriptionPlanSerializer,
    SubscriptionSerializer,
    TripSerializer,
)


class SubscriptionPlanViewSet(viewsets.ModelViewSet):
    queryset = SubscriptionPlan.objects.filter(is_active=True)
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [permissions.AllowAny()]
        if getattr(self.request.user, "role", None) == UserRoles.ADMIN:
            return [permissions.IsAdminUser()]
        return super().get_permissions()


class SubscriptionViewSet(viewsets.ModelViewSet):
    queryset = Subscription.objects.select_related("parent", "chauffeur", "plan")
    serializer_class = SubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ("status", "plan")
    search_fields = ("parent__email", "chauffeur__email")

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if getattr(user, "role", None) == UserRoles.PARENT:
            qs = qs.filter(parent=user)
        elif getattr(user, "role", None) == UserRoles.CHAUFFEUR:
            qs = qs.filter(chauffeur=user)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        subscription = self.get_object()
        subscription.activate()
        return Response({"detail": "Abonnement activé"})

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        subscription = self.get_object()
        subscription.suspend(reason=request.data.get("reason", "Suspension manuelle"))
        return Response({"detail": "Abonnement suspendu"})

    @action(detail=True, methods=["get"], permission_classes=[permissions.IsAuthenticated])
    def summary(self, request, pk=None):
        subscription = self.get_object()
        total_payments = subscription.payments.filter(status="success").aggregate(total=Sum("amount"))["total"]
        total_trips = subscription.trips.count()
        return Response(
            {
                "total_payments": total_payments or 0,
                "total_trips": total_trips,
                "status": subscription.status,
                "next_due_date": subscription.next_due_date,
            }
        )


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.select_related("subscription", "subscription__parent")
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ("status", "method")

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if getattr(user, "role", None) == UserRoles.PARENT:
            return qs.filter(subscription__parent=user)
        if getattr(user, "role", None) == UserRoles.CHAUFFEUR:
            return qs.filter(subscription__chauffeur=user)
        return qs

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def mark_paid(self, request, pk=None):
        payment = self.get_object()
        payment.status = "success"
        payment.provider_reference = payment.provider_reference or "manual-set"
        payment.save(update_fields=["status", "provider_reference"])
        subscription = payment.subscription
        subscription.last_payment_date = timezone.now().date()
        subscription.extend_next_due_date()
        NotificationLog.objects.create(
            user=subscription.parent,
            title="Paiement confirmé",
            message="Votre paiement a été confirmé manuellement par l'admin.",
            notification_type="payment_success",
            sent_via_email=True,
        )
        return Response({"detail": "Paiement marqué comme payé."})


class TripViewSet(viewsets.ModelViewSet):
    queryset = Trip.objects.select_related("subscription", "chauffeur", "parent")
    serializer_class = TripSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ("status", "scheduled_date")

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if getattr(user, "role", None) == UserRoles.PARENT:
            qs = qs.filter(parent=user)
        elif getattr(user, "role", None) == UserRoles.CHAUFFEUR:
            qs = qs.filter(chauffeur=user)
        return qs

    @action(detail=True, methods=["post"])
    def checkpoints(self, request, pk=None):
        trip = self.get_object()
        serializer = CheckpointSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(trip=trip)
        NotificationLog.objects.create(
            user=trip.parent,
            title="Mise à jour du trajet",
            message=f"Statut: {serializer.validated_data['checkpoint_type']}",
            notification_type="trip_update",
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CheckpointViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Checkpoint.objects.select_related("trip")
    serializer_class = CheckpointSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ("checkpoint_type",)

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if getattr(user, "role", None) == UserRoles.PARENT:
            return qs.filter(trip__parent=user)
        if getattr(user, "role", None) == UserRoles.CHAUFFEUR:
            return qs.filter(trip__chauffeur=user)
        return qs


class RideRequestViewSet(viewsets.ModelViewSet):
    queryset = RideRequest.objects.select_related("parent", "chauffeur", "trip")
    serializer_class = RideRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ("status",)
    search_fields = ("parent__username", "chauffeur__username", "pickup_location", "dropoff_location")

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if getattr(user, "role", None) == UserRoles.PARENT:
            qs = qs.filter(parent=user, parent_archived=False, requested_at__gte=timezone.now() - timezone.timedelta(days=7))
        elif getattr(user, "role", None) == UserRoles.CHAUFFEUR:
            qs = qs.filter(chauffeur=user, chauffeur_archived=False, requested_at__gte=timezone.now() - timezone.timedelta(days=7))
        return qs

    def perform_create(self, serializer):
        serializer.save(parent=self.request.user)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def accept(self, request, pk=None):
        ride_request = self.get_object()
        if request.user != ride_request.chauffeur:
            return Response({"detail": "Seul le chauffeur assigné peut accepter."}, status=status.HTTP_403_FORBIDDEN)
        trip = ride_request.accept()
        if trip:
            NotificationLog.objects.create(
                user=ride_request.parent,
                title="Course acceptée",
                message="Votre chauffeur a accepté la demande et arrive",
                notification_type="trip_update",
                sent_via_email=True,
            )
        return Response(self.get_serializer(ride_request).data)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def decline(self, request, pk=None):
        ride_request = self.get_object()
        if request.user != ride_request.chauffeur:
            return Response({"detail": "Seul le chauffeur assigné peut refuser."}, status=status.HTTP_403_FORBIDDEN)
        ride_request.decline(reason=request.data.get("reason"))
        NotificationLog.objects.create(
            user=ride_request.parent,
            title="Course refusée",
            message="Le chauffeur a décliné la demande.",
            notification_type="trip_update",
            sent_via_email=True,
        )
        return Response(self.get_serializer(ride_request).data)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def cancel(self, request, pk=None):
        ride_request = self.get_object()
        if request.user != ride_request.parent:
            return Response({"detail": "Seul l'abonné peut annuler la demande."}, status=status.HTTP_403_FORBIDDEN)
        ride_request.cancel()
        NotificationLog.objects.create(
            user=ride_request.chauffeur,
            title="Course annulée",
            message="La demande a été annulée par le particulier.",
            notification_type="trip_update",
        )
        return Response(self.get_serializer(ride_request).data)


class RatingViewSet(viewsets.ModelViewSet):
    queryset = Rating.objects.select_related("trip", "parent", "chauffeur")
    serializer_class = RatingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(parent=self.request.user)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = NotificationLog.objects.select_related("user")
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self.request.user, "role", None) != UserRoles.ADMIN:
            qs = qs.filter(user=self.request.user)
        return qs


class SOSAlertViewSet(viewsets.ModelViewSet):
    queryset = SOSAlert.objects.select_related("user")
    serializer_class = SOSAlertSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class MobileMoneyWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = MobileMoneyWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        return Response({"detail": "Webhook traité", "payment": PaymentSerializer(payment).data})


class StripeWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = StripeWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        return Response({"detail": "Stripe webhook traité", "payment": PaymentSerializer(payment).data})

