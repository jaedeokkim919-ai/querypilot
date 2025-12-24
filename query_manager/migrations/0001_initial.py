# Generated migration for QueryPilot

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='DatabaseConnection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='연결 이름')),
                ('host', models.CharField(max_length=255, verbose_name='호스트')),
                ('port', models.IntegerField(default=3306, verbose_name='포트')),
                ('database', models.CharField(blank=True, default='', max_length=100, verbose_name='데이터베이스명')),
                ('username', models.CharField(max_length=100, verbose_name='사용자명')),
                ('password', models.CharField(max_length=255, verbose_name='비밀번호')),
                ('schema', models.CharField(blank=True, default='', max_length=100, verbose_name='스키마')),
                ('is_active', models.BooleanField(default=True, verbose_name='활성화')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='생성일')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='수정일')),
            ],
            options={
                'verbose_name': '데이터베이스 연결',
                'verbose_name_plural': '데이터베이스 연결 목록',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='QueryExecution',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('query_text', models.TextField(verbose_name='쿼리')),
                ('query_type', models.CharField(choices=[('SELECT', 'SELECT'), ('INSERT', 'INSERT'), ('UPDATE', 'UPDATE'), ('DELETE', 'DELETE'), ('DDL', 'DDL'), ('OTHER', '기타')], default='OTHER', max_length=20, verbose_name='쿼리 유형')),
                ('executed_by', models.CharField(blank=True, max_length=100, verbose_name='실행자')),
                ('executed_at', models.DateTimeField(auto_now_add=True, verbose_name='실행 시간')),
                ('status', models.CharField(choices=[('SUCCESS', '성공'), ('FAILED', '실패')], default='SUCCESS', max_length=20, verbose_name='상태')),
                ('affected_rows', models.IntegerField(blank=True, null=True, verbose_name='영향받은 행')),
                ('execution_time', models.FloatField(default=0, verbose_name='실행 시간(초)')),
                ('error_message', models.TextField(blank=True, verbose_name='에러 메시지')),
                ('schema_before', models.TextField(blank=True, verbose_name='실행 전 스키마')),
                ('schema_after', models.TextField(blank=True, verbose_name='실행 후 스키마')),
                ('result_data', models.JSONField(blank=True, null=True, verbose_name='결과 데이터')),
                ('result_columns', models.JSONField(blank=True, null=True, verbose_name='결과 컬럼')),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='query_executions', to='query_manager.databaseconnection', verbose_name='연결')),
            ],
            options={
                'verbose_name': '쿼리 실행 이력',
                'verbose_name_plural': '쿼리 실행 이력 목록',
                'ordering': ['-executed_at'],
            },
        ),
        migrations.CreateModel(
            name='SchemaVersion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('table_name', models.CharField(max_length=255, verbose_name='테이블명')),
                ('version', models.IntegerField(default=1, verbose_name='버전')),
                ('schema_definition', models.TextField(verbose_name='스키마 정의')),
                ('checksum', models.CharField(max_length=64, verbose_name='체크섬')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='생성일')),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='schema_versions', to='query_manager.databaseconnection', verbose_name='연결')),
                ('query_execution', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='schema_versions', to='query_manager.queryexecution', verbose_name='관련 쿼리')),
            ],
            options={
                'verbose_name': '스키마 버전',
                'verbose_name_plural': '스키마 버전 목록',
                'ordering': ['connection', 'table_name', '-version'],
                'unique_together': {('connection', 'table_name', 'version')},
            },
        ),
        migrations.AddIndex(
            model_name='queryexecution',
            index=models.Index(fields=['connection', '-executed_at'], name='query_manag_connect_idx'),
        ),
        migrations.AddIndex(
            model_name='queryexecution',
            index=models.Index(fields=['query_type'], name='query_manag_query_t_idx'),
        ),
        migrations.AddIndex(
            model_name='queryexecution',
            index=models.Index(fields=['status'], name='query_manag_status_idx'),
        ),
        migrations.AddIndex(
            model_name='schemaversion',
            index=models.Index(fields=['connection', 'table_name'], name='query_manag_conn_table_idx'),
        ),
    ]
