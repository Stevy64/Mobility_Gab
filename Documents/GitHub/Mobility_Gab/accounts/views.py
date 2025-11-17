"""Views for handling authentication and profile management."""

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import DetailView, FormView, TemplateView

from core.models import NotificationLog, SOSAlert
from subscriptions.models import (
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionStatus,
    Trip,
)

from .forms import (
    ChauffeurProfileUpdateForm,
    ChauffeurRegistrationForm,
    LoginForm,
    ParentProfileUpdateForm,
    ParentRegistrationForm,
    ProfileUpdateForm,
    UserUpdateForm,
    PasswordUpdateForm,
)
from .models import UserRoles

User = get_user_model()


class LoginView(DjangoLoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm

    def form_valid(self, form):
        messages.success(self.request, "Connexion réussie. Bienvenue sur Mobility Gab !")
        return super().form_valid(form)


class LogoutView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/logout.html"

    def get(self, request, *args, **kwargs):
        logout(request)
        messages.info(request, "Vous êtes déconnecté. À bientôt !")
        return redirect("core:landing")


class RegisterView(FormView):
    template_name = "accounts/register.html"
    success_url = reverse_lazy("core:onboarding_success")

    def get_form_class(self):
        role = self.request.POST.get("role") or self.request.GET.get("role", UserRoles.PARENT)
        if role == UserRoles.CHAUFFEUR:
            return ChauffeurRegistrationForm
        return ParentRegistrationForm

    def get_initial(self):
        initial = super().get_initial()
        role = self.request.GET.get("role")
        if role in (UserRoles.PARENT, UserRoles.CHAUFFEUR):
            initial["role"] = role
        return initial

    def form_valid(self, form):
        user = form.save()
        raw_password = form.cleaned_data.get("password1")
        authenticated = authenticate(self.request, username=user.username, password=raw_password)
        if authenticated:
            login(self.request, authenticated)
        messages.success(self.request, "Compte créé. Configurez votre profil pour commencer.")
        return super().form_valid(form)


class ProfileView(LoginRequiredMixin, DetailView):
    template_name = "accounts/profile.html"

    def get_object(self, queryset=None):
        return self.request.user


class ProfileEditView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile_edit.html"

    def get_forms(self):
        user = self.request.user
        if self.request.method == "POST":
            user_form = UserUpdateForm(self.request.POST, instance=user)
            profile_form = ProfileUpdateForm(self.request.POST, self.request.FILES, instance=user.profile)
            password_form = PasswordUpdateForm(user, self.request.POST)
            parent_form = None
            chauffeur_form = None
            if user.role == UserRoles.PARENT and hasattr(user, "parent_profile"):
                parent_form = ParentProfileUpdateForm(self.request.POST, instance=user.parent_profile)
            if user.role == UserRoles.CHAUFFEUR and hasattr(user, "chauffeur_profile"):
                chauffeur_form = ChauffeurProfileUpdateForm(self.request.POST, self.request.FILES, instance=user.chauffeur_profile)
        else:
            user_form = UserUpdateForm(instance=user)
            profile_form = ProfileUpdateForm(instance=user.profile)
            password_form = PasswordUpdateForm(user)
            parent_form = None
            chauffeur_form = None
            if user.role == UserRoles.PARENT and hasattr(user, "parent_profile"):
                parent_form = ParentProfileUpdateForm(instance=user.parent_profile)
            if user.role == UserRoles.CHAUFFEUR and hasattr(user, "chauffeur_profile"):
                chauffeur_form = ChauffeurProfileUpdateForm(instance=user.chauffeur_profile)
        return user_form, profile_form, password_form, parent_form, chauffeur_form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_form, profile_form, password_form, parent_form, chauffeur_form = self.get_forms()
        context.update(
            {
                "user_form": user_form,
                "profile_form": profile_form,
                "password_form": password_form,
                "parent_form": parent_form,
                "chauffeur_form": chauffeur_form,
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        user_form, profile_form, password_form, parent_form, chauffeur_form = self.get_forms()
        forms_valid = user_form.is_valid() and profile_form.is_valid() and password_form.is_valid()
        if request.user.role == UserRoles.PARENT and parent_form is not None:
            forms_valid = forms_valid and parent_form.is_valid()
        if request.user.role == UserRoles.CHAUFFEUR and chauffeur_form is not None:
            forms_valid = forms_valid and chauffeur_form.is_valid()

        if forms_valid:
            user_form.save()
            profile_form.save()
            if parent_form is not None:
                parent_form.save()
            if chauffeur_form is not None:
                chauffeur_form.save()
            if password_form.should_change_password():
                request.user.set_password(password_form.cleaned_data["new_password"])
                request.user.save()
                messages.success(request, "Mot de passe modifié. Merci de vous reconnecter.")
                return redirect("accounts:login")
            messages.success(request, "Profil mis à jour avec succès.")
            return redirect("accounts:profile")

        messages.error(request, "Merci de corriger les erreurs ci-dessous.")
        context = {
            "user_form": user_form,
            "profile_form": profile_form,
            "password_form": password_form,
            "parent_form": parent_form,
            "chauffeur_form": chauffeur_form,
        }
        return self.render_to_response(context)


class StaffRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

    def handle_no_permission(self):
        messages.error(self.request, "Accès réservé à l'équipe admin.")
        return redirect("accounts:login")


class AdminDashboardView(StaffRequiredMixin, TemplateView):
    template_name = "accounts/admin_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        context.update(
            {
                "total_parents": User.objects.filter(role=UserRoles.PARENT).count(),
                "total_chauffeurs": User.objects.filter(role=UserRoles.CHAUFFEUR).count(),
                "active_subscriptions": Subscription.objects.filter(status=SubscriptionStatus.ACTIVE).count(),
                "pending_payments": Payment.objects.filter(status=PaymentStatus.PENDING).count(),
                "trips_today": Trip.objects.filter(scheduled_date=today).count(),
                "recent_subscriptions": Subscription.objects.select_related("parent", "chauffeur", "plan").order_by("-start_date")[:5],
                "recent_payments": Payment.objects.select_related("subscription", "subscription__parent", "subscription__chauffeur").order_by("-created_at")[:5],
                "recent_notifications": NotificationLog.objects.select_related("user").order_by("-created_at")[:10],
                "sos_alerts": SOSAlert.objects.order_by("-created_at")[:10],
            }
        )
        return context


class AdminParentsListView(StaffRequiredMixin, TemplateView):
    template_name = "accounts/admin_parents_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["parents"] = User.objects.filter(role=UserRoles.PARENT).select_related("profile")
        return context


class AdminChauffeursListView(StaffRequiredMixin, TemplateView):
    template_name = "accounts/admin_chauffeurs_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["chauffeurs"] = User.objects.filter(role=UserRoles.CHAUFFEUR).select_related("chauffeur_profile")
        return context
