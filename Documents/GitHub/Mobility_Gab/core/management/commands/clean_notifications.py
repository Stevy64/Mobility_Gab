"""
Commande Django pour nettoyer automatiquement les notifications.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import NotificationLog


class Command(BaseCommand):
    help = 'Nettoie les notifications anciennes et marquées comme lues'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='Nombre de jours après lesquels supprimer les notifications (défaut: 1)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Supprimer toutes les notifications sans exception'
        )

    def handle(self, *args, **options):
        days = options['days']
        force = options['force']
        
        self.stdout.write(f"🧹 Nettoyage des notifications...")
        
        if force:
            # Supprimer toutes les notifications
            count = NotificationLog.objects.all().delete()[0]
            self.stdout.write(
                self.style.SUCCESS(f"✅ {count} notifications supprimées (mode force)")
            )
        else:
            # Supprimer les notifications anciennes ou marquées comme lues
            cutoff_date = timezone.now() - timezone.timedelta(days=days)
            
            # Notifications marquées comme lues
            read_count = NotificationLog.objects.filter(read=True).delete()[0]
            
            # Notifications anciennes
            old_count = NotificationLog.objects.filter(
                created_at__lt=cutoff_date
            ).delete()[0]
            
            # Notifications avec auto_delete_at dépassé
            expired_count = NotificationLog.objects.filter(
                auto_delete_at__lt=timezone.now()
            ).delete()[0]
            
            total = read_count + old_count + expired_count
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ {total} notifications supprimées:\n"
                    f"   - Marquées comme lues: {read_count}\n"
                    f"   - Anciennes (>={days} jours): {old_count}\n"
                    f"   - Auto-suppression: {expired_count}"
                )
            )
        
        # Afficher le nombre restant
        remaining = NotificationLog.objects.count()
        if remaining > 0:
            self.stdout.write(
                self.style.WARNING(f"⚠️  {remaining} notifications restantes")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("🎉 Aucune notification restante !")
            )

