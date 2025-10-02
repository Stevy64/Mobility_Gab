"""
Commande Django pour nettoyer spécifiquement les notifications de chat.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import NotificationLog


class Command(BaseCommand):
    help = 'Nettoie les notifications de chat persistantes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Supprimer toutes les notifications sans exception'
        )

    def handle(self, *args, **options):
        force = options['force']
        
        self.stdout.write("🧹 Nettoyage des notifications de chat...")
        
        if force:
            # Supprimer toutes les notifications
            count = NotificationLog.objects.all().delete()[0]
            self.stdout.write(
                self.style.SUCCESS(f"✅ {count} notifications supprimées (mode force)")
            )
        else:
            # Supprimer spécifiquement les notifications de chat
            deleted_count = 0
            
            # 1. Notifications de type chat_message
            chat_count = NotificationLog.objects.filter(notification_type="chat_message").delete()[0]
            deleted_count += chat_count
            if chat_count > 0:
                self.stdout.write(f"   - {chat_count} notifications 'chat_message' supprimées")
            
            # 2. Notifications avec "Message de" dans le titre
            message_count = NotificationLog.objects.filter(title__icontains="Message de").delete()[0]
            deleted_count += message_count
            if message_count > 0:
                self.stdout.write(f"   - {message_count} notifications 'Message de' supprimées")
            
            # 3. Notifications avec emoji 💬
            emoji_count = NotificationLog.objects.filter(title__icontains="💬").delete()[0]
            deleted_count += emoji_count
            if emoji_count > 0:
                self.stdout.write(f"   - {emoji_count} notifications avec emoji supprimées")
            
            self.stdout.write(
                self.style.SUCCESS(f"✅ {deleted_count} notifications de chat supprimées")
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




