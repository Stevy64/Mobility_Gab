# Mobility Gab – MVP Marketplace de transport

Mobility Gab est une plateforme Django + Django REST Framework reliée à des templates Bootstrap 5 pour connecter particuliers et chauffeurs autour d’abonnements et de courses à la demande. Une API REST documentée alimente les futures apps mobiles (React Native / Flutter).

## Fonctionnalités clés

- Authentification email + mot de passe, connexion via **nom d’utilisateur**.
- Profils complets (photo, téléphone, adresse, permis, véhicule). **Formulaire d’édition** pour particuliers et chauffeurs.
- Gestion d’abonnements avec statut (actif, overdue, suspendu), historique, paiements mock Mobile Money/Stripe.
- **Demandes de course ponctuelle** (ride requests) : un particulier envoie sa course, le chauffeur peut accepter/refuser. Notifications email/in-app et création automatique d’un trajet.
- Suivi & checkpoints : simulation GPS, notification des étapes (en route, arrivé, etc.).
- Tableau de bord staff (`is_staff`) : statistiques, abonnements/paiements récents, alertes SOS, notifications, listings chauffeurs/particuliers et accès rapide à leurs dashboards.
- API REST (JWT) + Swagger/Redoc.
- Celery + Redis pour relances automatiques des paiements.

## Installation & lancement

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Adapter les variables (SECRET_KEY, DATABASE_URL, brokers Celery...)

python manage.py migrate
python manage.py loaddata accounts/fixtures/initial_users.json
python manage.py loaddata accounts/fixtures/sample_users.json
python manage.py loaddata subscriptions/fixtures/sample_subscriptions.json

python manage.py runserver
```

### Services complémentaires

- **Celery worker** : `celery -A mobisure worker -l info`
- **Celery beat** : `celery -A mobisure beat -l info`
- **Redis** : requis pour le broker (utiliser `redis://localhost:6379/0` ou équivalent).

## Workflows à tester

### Création / édition de profil
1. Créer un compte (particulier / chauffeur / compte staff créé via superuser).
2. Se connecter avec le **nom d’utilisateur** choisi.
3. Page Profil (`accounts/profile/`) → bouton « Modifier » :
   - Informations compte et contact.
   - Champs spécifiques (contacts d’urgence, véhicule, position, disponibilité).
   - **Changement de mot de passe** (laisser vide si aucune modification).

### Demandes de course ponctuelle
1. Particulier : `subscriptions/ride-requests/new/` → définir départ/destination (option zone).
2. Chauffeurs éligibles listés; la demande attribue automatiquement le mieux placé/disponible.
3. Historique particulier : `subscriptions/ride-requests/parent/` + détail.
4. Chauffeur : `subscriptions/ride-requests/chauffeur/` pour accepter/refuser.
5. Acceptation démarre un `Trip` (tracking bientôt) et envoie notification.

### 🆕 Nouvelles fonctionnalités avancées

#### Géolocalisation et matching intelligent
- **Calcul de distance GPS** : Utilise la formule de Haversine pour calculer les distances réelles
- **Matching avancé** : Trouve les chauffeurs dans un rayon défini (10km par défaut)
- **Estimation d'arrivée** : Calcule l'ETA basé sur la position GPS et vitesse moyenne
- **Zones dynamiques** : Génération automatique de zones basées sur les coordonnées

#### Suivi GPS en temps réel
- **Carte interactive** : Suivi live avec Leaflet/OpenStreetMap
- **Checkpoints automatiques** : EN_ROUTE, ARRIVÉ, ENFANT_DÉPOSÉ, etc.
- **Position chauffeur** : Mise à jour GPS toutes les 10 secondes
- **Partage de position** : Lien de suivi partageable
- **Interface responsive** : Optimisée mobile avec actions rapides

#### Système de notifications avancé
- **Multi-canaux** : Push, SMS, Email, In-app
- **Notifications intelligentes** : Basées sur les préférences utilisateur
- **Polling temps réel** : Mises à jour automatiques sans rechargement
- **Templates personnalisés** : Emails HTML avec design responsive
- **Système SOS** : Alertes d'urgence prioritaires

#### Historiques et statistiques détaillés
- **Tableaux de bord** : Statistiques complètes avec graphiques
- **Historique filtrable** : Par statut, période, chauffeur
- **Export de données** : CSV pour comptabilité/archives
- **Analyses visuelles** : Charts.js pour évolution mensuelle
- **Détails de course** : Modal avec toutes les informations

### URLs des nouvelles fonctionnalités

#### Suivi et historique
- `subscriptions/tracking/<trip_id>/` : Suivi GPS temps réel
- `subscriptions/history/` : Historique détaillé avec stats
- `subscriptions/api/trips/<trip_id>/location/` : API position chauffeur
- `subscriptions/api/trips/export/` : Export CSV

#### Notifications et SOS
- `core/api/polling/` : Polling pour mises à jour temps réel
- `core/api/sos/` : Déclencher alerte SOS
- `core/api/notifications/preferences/` : Gérer préférences
- `core/api/push/subscribe/` : Abonnement notifications push

#### APIs chauffeur
- `subscriptions/api/chauffeur/location/` : Mettre à jour position GPS
- `subscriptions/api/trips/<trip_id>/checkpoint/` : Créer checkpoint

### Technologies utilisées
- **Cartes** : Leaflet + OpenStreetMap (gratuit, pas de clé API)
- **Graphiques** : Chart.js pour statistiques
- **Temps réel** : Polling JavaScript + APIs Django
- **Géolocalisation** : Formule Haversine + API Geolocation
- **Notifications** : Système multi-canaux avec templates
- **Export** : CSV natif Python

### Espace admin staff
1. Créer un superuser : `python manage.py createsuperuser` (nom d’utilisateur requis).
2. Se connecter avec ce compte → un onglet « Espace admin » apparaît.
3. Tableaux de bord staff : stats, abonnements/paiements récents, alertes SOS, etc. Boutons pour accéder aux listes complètes de particuliers et chauffeurs, avec lien direct vers leurs dashboards.

## Routes web utiles

- `accounts/profile/` & `accounts/profile/edit/`
- `subscriptions/ride-requests/new/`
- `subscriptions/ride-requests/parent/`
- `subscriptions/ride-requests/chauffeur/`
- `accounts/admin/dashboard/`, `accounts/admin/parents/`, `accounts/admin/chauffeurs/`

## API REST (extraits)
- `/api/ride-requests/` (CRUD + `accept/decline/cancel` via actions)
- `/api/trips/`, `/api/checkpoints/`
- `/api/subscriptions/`, `/api/payments/`

## Points d’amélioration futurs
- Matching géographique avancé (lat/long, distance réelle).
- Suivi temps réel enrichi (WebSockets, carte interactive, envoi de checkpoints automatiques).
- Notifications push/SMS en production.
- Planificateur de trajets récurrents, reporting analytics complet.
- Tests automatisés (désactivés pendant cette phase de développement).

---
Clonez, installez et commencez à orchestrer vos transports en toute sérénité avec Mobility Gab !


