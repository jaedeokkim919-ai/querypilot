# Generated migration for adding hosts field to DatabaseConnection

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('query_manager', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='databaseconnection',
            name='hosts',
            field=models.TextField(
                blank=True,
                default='',
                help_text='여러 호스트를 줄바꿈으로 구분',
                verbose_name='호스트 목록'
            ),
        ),
    ]
