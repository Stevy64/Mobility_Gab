from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0006_trip_chauffeur_confirmed_completion_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='trip',
            name='chauffeur_archived',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='trip',
            name='parent_archived',
            field=models.BooleanField(default=False),
        ),
    ]
