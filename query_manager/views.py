"""
QueryPilot 뷰
"""

import json
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta

from .models import DatabaseConnection, QueryExecution, SchemaVersion
from .forms import (
    DatabaseConnectionForm,
    DatabaseConnectionEditForm,
    QueryExecuteForm,
    HistoryFilterForm
)
from .services import QueryService


# ============ Dashboard ============
class DashboardView(View):
    """대시보드 뷰"""

    def get(self, request):
        connections = DatabaseConnection.objects.filter(is_active=True)
        recent_queries = QueryExecution.objects.select_related('connection')[:10]

        # 통계
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)

        stats = {
            'total_connections': connections.count(),
            'total_queries_today': QueryExecution.objects.filter(
                executed_at__date=today
            ).count(),
            'failed_queries_today': QueryExecution.objects.filter(
                executed_at__date=today,
                status='FAILED'
            ).count(),
            'queries_this_week': QueryExecution.objects.filter(
                executed_at__date__gte=week_ago
            ).count(),
        }

        # 연결별 쿼리 수
        connection_stats = QueryExecution.objects.values(
            'connection__name'
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:5]

        context = {
            'connections': connections,
            'recent_queries': recent_queries,
            'stats': stats,
            'connection_stats': connection_stats,
        }
        return render(request, 'query_manager/dashboard.html', context)


# ============ Connection Views ============
class ConnectionListView(ListView):
    """연결 목록 뷰"""
    model = DatabaseConnection
    template_name = 'query_manager/connection_list.html'
    context_object_name = 'connections'


class ConnectionDetailView(DetailView):
    """연결 상세 뷰"""
    model = DatabaseConnection
    template_name = 'query_manager/connection_detail.html'
    context_object_name = 'connection'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connection = self.object

        # 최근 쿼리 이력
        context['recent_queries'] = QueryExecution.objects.filter(
            connection=connection
        )[:10]

        # 스키마 버전 (테이블별 최신)
        context['schema_versions'] = SchemaVersion.objects.filter(
            connection=connection
        ).order_by('table_name', '-version').distinct('table_name')[:10] if False else \
            SchemaVersion.objects.filter(connection=connection).order_by('-created_at')[:10]

        return context


class ConnectionCreateView(CreateView):
    """연결 생성 뷰"""
    model = DatabaseConnection
    form_class = DatabaseConnectionForm
    template_name = 'query_manager/connection_form.html'
    success_url = reverse_lazy('query_manager:connection_list')

    def form_valid(self, form):
        messages.success(self.request, f'연결 "{form.instance.name}"이(가) 생성되었습니다.')
        return super().form_valid(form)


class ConnectionUpdateView(UpdateView):
    """연결 수정 뷰"""
    model = DatabaseConnection
    form_class = DatabaseConnectionEditForm
    template_name = 'query_manager/connection_form.html'
    success_url = reverse_lazy('query_manager:connection_list')

    def form_valid(self, form):
        messages.success(self.request, f'연결 "{form.instance.name}"이(가) 수정되었습니다.')
        return super().form_valid(form)


class ConnectionDeleteView(DeleteView):
    """연결 삭제 뷰"""
    model = DatabaseConnection
    template_name = 'query_manager/connection_confirm_delete.html'
    success_url = reverse_lazy('query_manager:connection_list')

    def delete(self, request, *args, **kwargs):
        connection = self.get_object()
        messages.success(request, f'연결 "{connection.name}"이(가) 삭제되었습니다.')
        return super().delete(request, *args, **kwargs)


# ============ Query Editor Views ============
class QueryEditorView(View):
    """쿼리 에디터 뷰"""

    def get(self, request):
        connection_id = request.GET.get('connection')
        connections = DatabaseConnection.objects.filter(is_active=True)

        selected_connection = None
        databases = []

        if connection_id:
            try:
                selected_connection = DatabaseConnection.objects.get(pk=connection_id)
                service = QueryService(selected_connection)
                databases = service.get_databases()
            except DatabaseConnection.DoesNotExist:
                pass

        context = {
            'connections': connections,
            'selected_connection': selected_connection,
            'databases': databases,
            'form': QueryExecuteForm(initial={'connection': selected_connection}),
        }
        return render(request, 'query_manager/query_editor.html', context)


class QueryExecuteView(View):
    """쿼리 실행 API"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            connection_id = data.get('connection_id')
            query = data.get('query', '').strip()
            executed_by = request.user.username if request.user.is_authenticated else 'anonymous'

            if not connection_id:
                return JsonResponse({'success': False, 'error': '연결을 선택해주세요.'})

            if not query:
                return JsonResponse({'success': False, 'error': '쿼리를 입력해주세요.'})

            connection = get_object_or_404(DatabaseConnection, pk=connection_id)
            service = QueryService(connection)

            # ALTER 문인 경우 분석 결과 포함
            alter_analysis = None
            if query.strip().upper().startswith('ALTER'):
                alter_analysis = service.analyze_alter_statement(query)

            result = service.execute_query(query, executed_by)
            result['alter_analysis'] = alter_analysis

            return JsonResponse(result)

        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': '잘못된 요청 형식입니다.'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class AlterAnalyzeView(View):
    """ALTER 문 분석 API"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            connection_id = data.get('connection_id')
            query = data.get('query', '').strip()

            if not connection_id:
                return JsonResponse({'success': False, 'error': '연결을 선택해주세요.'})

            connection = get_object_or_404(DatabaseConnection, pk=connection_id)
            service = QueryService(connection)
            result = service.analyze_alter_statement(query)
            result['success'] = True

            return JsonResponse(result)

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


# ============ History Views ============
class HistoryListView(View):
    """히스토리 목록 뷰"""

    def get(self, request):
        form = HistoryFilterForm(request.GET)
        queryset = QueryExecution.objects.select_related('connection').all()

        if form.is_valid():
            if form.cleaned_data.get('connection'):
                queryset = queryset.filter(connection=form.cleaned_data['connection'])
            if form.cleaned_data.get('query_type'):
                queryset = queryset.filter(query_type=form.cleaned_data['query_type'])
            if form.cleaned_data.get('status'):
                queryset = queryset.filter(status=form.cleaned_data['status'])
            if form.cleaned_data.get('search'):
                queryset = queryset.filter(query_text__icontains=form.cleaned_data['search'])
            if form.cleaned_data.get('date_from'):
                queryset = queryset.filter(executed_at__date__gte=form.cleaned_data['date_from'])
            if form.cleaned_data.get('date_to'):
                queryset = queryset.filter(executed_at__date__lte=form.cleaned_data['date_to'])

        # 페이지네이션
        from django.core.paginator import Paginator
        paginator = Paginator(queryset, 50)
        page = request.GET.get('page', 1)
        executions = paginator.get_page(page)

        context = {
            'form': form,
            'executions': executions,
        }
        return render(request, 'query_manager/history_list.html', context)


class HistoryDetailView(DetailView):
    """히스토리 상세 뷰"""
    model = QueryExecution
    template_name = 'query_manager/history_detail.html'
    context_object_name = 'execution'


# ============ Schema Views ============
class SchemaVersionListView(View):
    """스키마 버전 목록 뷰"""

    def get(self, request, pk):
        connection = get_object_or_404(DatabaseConnection, pk=pk)
        table_name = request.GET.get('table')

        versions = SchemaVersion.objects.filter(connection=connection)
        if table_name:
            versions = versions.filter(table_name=table_name)

        # 테이블 목록
        tables = SchemaVersion.objects.filter(
            connection=connection
        ).values_list('table_name', flat=True).distinct()

        context = {
            'connection': connection,
            'versions': versions.order_by('table_name', '-version'),
            'tables': tables,
            'selected_table': table_name,
        }
        return render(request, 'query_manager/schema_version_list.html', context)


class SchemaDiffView(View):
    """스키마 Diff API"""

    def get(self, request, pk):
        connection = get_object_or_404(DatabaseConnection, pk=pk)
        table_name = request.GET.get('table')
        version1 = request.GET.get('v1')
        version2 = request.GET.get('v2')

        if not table_name:
            return JsonResponse({'error': '테이블명이 필요합니다.'})

        service = QueryService(connection)
        result = service.get_schema_diff(
            table_name,
            int(version1) if version1 else None,
            int(version2) if version2 else None
        )

        return JsonResponse(result)


# ============ API Views ============
class ApiConnectionTestView(View):
    """연결 테스트 API"""

    def post(self, request, pk):
        connection = get_object_or_404(DatabaseConnection, pk=pk)
        service = QueryService(connection)
        result = service.test_connection()
        return JsonResponse(result)


class ApiDatabasesView(View):
    """데이터베이스 목록 API"""

    def get(self, request, pk):
        connection = get_object_or_404(DatabaseConnection, pk=pk)
        service = QueryService(connection)
        databases = service.get_databases()
        return JsonResponse({'databases': databases})


class ApiTablesView(View):
    """테이블 목록 API"""

    def get(self, request, pk):
        connection = get_object_or_404(DatabaseConnection, pk=pk)
        service = QueryService(connection)
        tables = service.get_all_tables()
        return JsonResponse({'tables': tables})


class ApiTableSchemaView(View):
    """테이블 스키마 API"""

    def get(self, request, pk, table_name):
        connection = get_object_or_404(DatabaseConnection, pk=pk)
        service = QueryService(connection)
        schema = service.get_table_schema(table_name)
        return JsonResponse({'schema': schema})
