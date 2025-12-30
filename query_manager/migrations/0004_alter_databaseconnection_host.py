from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('query_manager', '0003_merge_20251229_1913'),
    ]

    operations = [
        migrations.AlterField(
            model_name='databaseconnection',
            name='host',
            field=models.CharField(blank=True, default='', max_length=255, verbose_name='호스트'),
        ),
    ]
