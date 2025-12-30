from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('query_manager', '0002_databaseconnection_hosts'),
    ]

    operations = [
        migrations.AlterField(
            model_name='databaseconnection',
            name='host',
            field=models.CharField(blank=True, default='', max_length=255, verbose_name='호스트'),
        ),
    ]
