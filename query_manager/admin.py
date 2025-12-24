from django.contrib import admin
from .models import DatabaseConnection, QueryExecution, SchemaVersion


@admin.register(DatabaseConnection)
class DatabaseConnectionAdmin(admin.ModelAdmin):
    list_display = ['name', 'host', 'port', 'database', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'host', 'database']


@admin.register(QueryExecution)
class QueryExecutionAdmin(admin.ModelAdmin):
    list_display = ['connection', 'query_type', 'status', 'affected_rows', 'execution_time', 'executed_at']
    list_filter = ['status', 'query_type', 'executed_at', 'connection']
    search_fields = ['query_text', 'connection__name']
    readonly_fields = ['executed_at']


@admin.register(SchemaVersion)
class SchemaVersionAdmin(admin.ModelAdmin):
    list_display = ['connection', 'table_name', 'version', 'checksum', 'created_at']
    list_filter = ['connection', 'created_at']
    search_fields = ['table_name', 'connection__name']
    readonly_fields = ['created_at', 'checksum']
