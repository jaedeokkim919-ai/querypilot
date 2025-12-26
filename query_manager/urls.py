from django.urls import path
from . import views

app_name = 'query_manager'

urlpatterns = [
    # Dashboard
    path('', views.DashboardView.as_view(), name='dashboard'),

    # Database Connections
    path('connections/', views.ConnectionListView.as_view(), name='connection_list'),
    path('connections/create/', views.ConnectionCreateView.as_view(), name='connection_create'),
    path('connections/<int:pk>/', views.ConnectionDetailView.as_view(), name='connection_detail'),
    path('connections/<int:pk>/edit/', views.ConnectionUpdateView.as_view(), name='connection_edit'),
    path('connections/<int:pk>/delete/', views.ConnectionDeleteView.as_view(), name='connection_delete'),

    # Query Editor
    path('query/', views.QueryEditorView.as_view(), name='query_editor'),
    path('query/execute/', views.QueryExecuteView.as_view(), name='query_execute'),
    path('query/analyze-alter/', views.AlterAnalyzeView.as_view(), name='alter_analyze'),
    path('query/review/', views.QueryReviewView.as_view(), name='query_review'),
    path('query/batch-execute/', views.QueryBatchExecuteView.as_view(), name='query_batch_execute'),

    # History
    path('history/', views.HistoryListView.as_view(), name='history_list'),
    path('history/<int:pk>/', views.HistoryDetailView.as_view(), name='history_detail'),
    path('history/<int:pk>/schema-compare/', views.HistorySchemaCompareView.as_view(), name='history_schema_compare'),

    # Schema Versions
    path('connections/<int:pk>/schema/', views.SchemaVersionListView.as_view(), name='schema_version_list'),
    path('connections/<int:pk>/schema/diff/', views.SchemaDiffView.as_view(), name='schema_diff'),

    # Version Management
    path('versions/', views.VersionManagementView.as_view(), name='version_management'),
    path('versions/timeline/<int:connection_id>/<str:table_name>/', views.VersionTimelineView.as_view(), name='version_timeline'),
    path('versions/compare/', views.VersionCompareView.as_view(), name='version_compare'),
    path('versions/<int:version_id>/rollback-ddl/', views.VersionRollbackDDLView.as_view(), name='version_rollback_ddl'),
    path('versions/<int:version_id>/tag/', views.VersionTagView.as_view(), name='version_tag'),

    # API Endpoints
    path('api/connections/<int:pk>/test/', views.ApiConnectionTestView.as_view(), name='api_connection_test'),
    path('api/connections/<int:pk>/databases/', views.ApiDatabasesView.as_view(), name='api_databases'),
    path('api/connections/<int:pk>/tables/', views.ApiTablesView.as_view(), name='api_tables'),
    path('api/connections/<int:pk>/tables/<str:table_name>/schema/', views.ApiTableSchemaView.as_view(), name='api_table_schema'),
    path('api/connections/<int:pk>/databases/<str:database>/tables/', views.ApiTablesWithDatabaseView.as_view(), name='api_database_tables'),
]
