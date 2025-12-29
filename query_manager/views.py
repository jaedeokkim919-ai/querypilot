"""
QueryPilot 뷰
"""

import json
import uuid
import time
import threading
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta

# 배치 실행 진행 상황 저장 (메모리 기반 - 프로덕션에서는 Redis 등 사용 권장)
batch_progress_store = {}

from .models import DatabaseConnection, QueryExecution, SchemaVersion, SchemaVersionTag
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
            'today': today.strftime('%Y-%m-%d'),
            'week_ago': week_ago.strftime('%Y-%m-%d'),
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
            operator = data.get('operator', '').strip()
            database = data.get('database', '').strip()

            # 작업자(operator)를 executed_by로 사용
            executed_by = operator if operator else (
                request.user.username if request.user.is_authenticated else 'anonymous'
            )

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

            # 다중 서버 지원: 호스트가 여러 개인 경우
            if connection.is_multi_server():
                result = service.execute_query_multi_server(query, database, executed_by)
                result['is_multi_server'] = True
                result['alter_analysis'] = alter_analysis
                # 전체 성공 여부
                result['success'] = result['failed_hosts'] == 0
            else:
                result = service.execute_query(query, executed_by)
                result['is_multi_server'] = False
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

            # 카테고리 필터
            category = form.cleaned_data.get('category')
            if category == 'DDL':
                queryset = queryset.filter(query_type='DDL')
            elif category == 'DML':
                queryset = queryset.filter(query_type__in=['INSERT', 'UPDATE', 'DELETE'])
            elif category == 'DQL':
                queryset = queryset.filter(query_type='SELECT')

            # 작업자 필터
            if form.cleaned_data.get('operator'):
                queryset = queryset.filter(operator__icontains=form.cleaned_data['operator'])

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

        # 다중 서버 지원
        if connection.is_multi_server():
            result = service.test_connection_multi_server()
            result['is_multi_server'] = True
            # 전체 성공 여부
            result['success'] = result['failed_hosts'] == 0
            result['message'] = f"{result['successful_hosts']}/{result['total_hosts']} 서버 연결 성공"
        else:
            result = service.test_connection()
            result['is_multi_server'] = False

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


class ApiTablesWithDatabaseView(View):
    """특정 데이터베이스의 테이블 목록 API"""

    def get(self, request, pk, database):
        connection = get_object_or_404(DatabaseConnection, pk=pk)
        service = QueryService(connection)
        tables = service.get_tables_with_database(database)
        return JsonResponse({'tables': tables})


# ============ Query Review & Batch Execution ============
class QueryReviewView(View):
    """쿼리 검수 API"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            connection_id = data.get('connection_id')
            query_text = data.get('query', '').strip()
            operator = data.get('operator', '').strip()

            if not connection_id:
                return JsonResponse({'success': False, 'error': '연결을 선택해주세요.'})

            if not query_text:
                return JsonResponse({'success': False, 'error': '쿼리를 입력해주세요.'})

            if not operator:
                return JsonResponse({'success': False, 'error': '작업자를 입력해주세요.'})

            connection = get_object_or_404(DatabaseConnection, pk=connection_id)
            service = QueryService(connection)

            # 쿼리 분리
            queries = service.split_queries(query_text)

            # 각 쿼리 검증
            validation_results = []
            all_valid = True
            has_dangerous = False

            for idx, query in enumerate(queries):
                result = service.validate_query(query)
                result['index'] = idx
                result['query'] = query[:100] + '...' if len(query) > 100 else query
                result['full_query'] = query
                validation_results.append(result)

                if not result['valid']:
                    all_valid = False
                if result['is_dangerous']:
                    has_dangerous = True

            return JsonResponse({
                'success': True,
                'all_valid': all_valid,
                'has_dangerous': has_dangerous,
                'query_count': len(queries),
                'validation_results': validation_results,
                'operator': operator
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class QueryBatchExecuteView(View):
    """배치 쿼리 실행 API"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            connection_id = data.get('connection_id')
            queries = data.get('queries', [])
            operator = data.get('operator', '').strip()

            if not connection_id:
                return JsonResponse({'success': False, 'error': '연결을 선택해주세요.'})

            if not queries:
                return JsonResponse({'success': False, 'error': '실행할 쿼리가 없습니다.'})

            if not operator:
                return JsonResponse({'success': False, 'error': '작업자를 입력해주세요.'})

            connection = get_object_or_404(DatabaseConnection, pk=connection_id)
            service = QueryService(connection)

            result = service.execute_batch(queries, operator)
            return JsonResponse(result)

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


# ============ Version Management Views ============
class VersionManagementView(View):
    """버전 관리 메인 뷰"""

    def get(self, request):
        # AJAX 요청: 테이블 목록 조회
        action = request.GET.get('action')
        connection_id = request.GET.get('connection_id') or request.GET.get('connection')

        if action == 'get_tables' and connection_id:
            try:
                connection = DatabaseConnection.objects.get(pk=connection_id)
                tables = SchemaVersion.objects.filter(
                    connection=connection
                ).values('table_name').annotate(
                    version_count=Count('id')
                ).order_by('table_name')

                return JsonResponse({
                    'tables': list(tables)
                })
            except DatabaseConnection.DoesNotExist:
                return JsonResponse({'error': '연결을 찾을 수 없습니다.'})

        # 일반 페이지 렌더링
        connections = DatabaseConnection.objects.filter(is_active=True)

        selected_connection = None
        tables_with_versions = []
        selected_table = request.GET.get('table')
        versions = []

        if connection_id:
            try:
                selected_connection = DatabaseConnection.objects.get(pk=connection_id)

                # 버전이 있는 테이블 목록
                tables_with_versions = SchemaVersion.objects.filter(
                    connection=selected_connection
                ).values('table_name').annotate(
                    version_count=Count('id'),
                    latest_version=Count('version')
                ).order_by('table_name')

                # 선택된 테이블의 버전 목록
                if selected_table:
                    versions = SchemaVersion.objects.filter(
                        connection=selected_connection,
                        table_name=selected_table
                    ).order_by('-version')

            except DatabaseConnection.DoesNotExist:
                pass

        context = {
            'connections': connections,
            'selected_connection': int(connection_id) if connection_id else None,
            'tables_with_versions': tables_with_versions,
            'selected_table': selected_table,
            'versions': versions,
        }
        return render(request, 'query_manager/version_management.html', context)


class VersionTimelineView(View):
    """버전 타임라인 API"""

    def get(self, request, connection_id, table_name):
        connection = get_object_or_404(DatabaseConnection, pk=connection_id)

        versions_qs = SchemaVersion.objects.filter(
            connection=connection,
            table_name=table_name
        ).order_by('-version')

        versions = []
        for v in versions_qs:
            tags = list(v.tags.values('id', 'tag_name', 'memo', 'created_by'))

            versions.append({
                'id': v.id,
                'version': v.version,
                'captured_at': v.created_at.strftime('%Y-%m-%d %H:%M:%S') if v.created_at else None,
                'executed_by': v.executed_by,
                'change_summary': v.change_summary,
                'ddl_type': v.ddl_type,
                'schema_definition': v.schema_definition,
                'tags': tags
            })

        return JsonResponse({'versions': versions, 'table_name': table_name})


class VersionCompareView(View):
    """버전 비교 API"""

    def get(self, request):
        # 파라미터 호환성 (v1/v2 또는 from_id/to_id)
        version1_id = request.GET.get('from_id') or request.GET.get('v1')
        version2_id = request.GET.get('to_id') or request.GET.get('v2')

        if not version1_id or not version2_id:
            return JsonResponse({'error': '두 버전을 선택해주세요.'})

        try:
            v1 = SchemaVersion.objects.get(pk=version1_id)
            service = QueryService(v1.connection)
            result = service.compare_schema_versions(int(version1_id), int(version2_id))
            return JsonResponse(result)
        except SchemaVersion.DoesNotExist:
            return JsonResponse({'error': '버전을 찾을 수 없습니다.'})
        except Exception as e:
            return JsonResponse({'error': str(e)})


class VersionRollbackDDLView(View):
    """롤백 DDL 생성 API"""

    def get(self, request, version_id):
        # 파라미터 호환성 (to 또는 target_version_id)
        target_version_id = request.GET.get('target_version_id') or request.GET.get('to')

        if not target_version_id:
            return JsonResponse({'error': '롤백 대상 버전을 선택해주세요.'})

        try:
            current_version = SchemaVersion.objects.get(pk=version_id)
            service = QueryService(current_version.connection)
            result = service.generate_rollback_ddl(int(version_id), int(target_version_id))
            return JsonResponse(result)
        except SchemaVersion.DoesNotExist:
            return JsonResponse({'error': '버전을 찾을 수 없습니다.'})
        except Exception as e:
            return JsonResponse({'error': str(e)})


class VersionTagView(View):
    """버전 태그/메모 CRUD API"""

    def get(self, request, version_id):
        """태그 목록 조회"""
        try:
            version = SchemaVersion.objects.get(pk=version_id)
            tags = list(version.tags.values('id', 'tag_name', 'memo', 'created_at', 'created_by'))
            return JsonResponse({'tags': tags})
        except SchemaVersion.DoesNotExist:
            return JsonResponse({'error': '버전을 찾을 수 없습니다.'})

    def post(self, request, version_id):
        """태그 추가"""
        try:
            data = json.loads(request.body)
            version = SchemaVersion.objects.get(pk=version_id)

            tag = SchemaVersionTag.objects.create(
                schema_version=version,
                tag_name=data.get('tag_name', ''),
                memo=data.get('memo', ''),
                created_by=data.get('created_by', '')
            )

            return JsonResponse({
                'success': True,
                'tag': {
                    'id': tag.id,
                    'tag_name': tag.tag_name,
                    'memo': tag.memo,
                    'created_at': tag.created_at.isoformat(),
                    'created_by': tag.created_by
                }
            })
        except SchemaVersion.DoesNotExist:
            return JsonResponse({'success': False, 'error': '버전을 찾을 수 없습니다.'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    def delete(self, request, version_id):
        """태그 삭제"""
        try:
            # DELETE 요청은 query parameter에서 tag_id를 가져옴
            tag_id = request.GET.get('tag_id')

            if not tag_id:
                return JsonResponse({'success': False, 'error': '태그 ID가 필요합니다.'})

            tag = SchemaVersionTag.objects.get(pk=tag_id, schema_version_id=version_id)
            tag.delete()

            return JsonResponse({'success': True})
        except SchemaVersionTag.DoesNotExist:
            return JsonResponse({'success': False, 'error': '태그를 찾을 수 없습니다.'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class HistorySchemaCompareView(View):
    """히스토리 스키마 비교 API"""

    def get(self, request, pk):
        import difflib

        execution = get_object_or_404(QueryExecution, pk=pk)

        if execution.query_type != 'DDL':
            return JsonResponse({'error': 'DDL 쿼리가 아닙니다.'})

        before_schema = execution.schema_before or ''
        after_schema = execution.schema_after or ''

        # 테이블명 추출 시도
        table_name = ''
        query_upper = execution.query_text.upper()
        for keyword in ['TABLE', 'INDEX ON']:
            if keyword in query_upper:
                parts = execution.query_text.split()
                try:
                    idx = [p.upper() for p in parts].index(keyword.split()[0])
                    if keyword == 'INDEX ON':
                        idx = [p.upper() for p in parts].index('ON')
                    table_name = parts[idx + 1].strip('`"[]();')
                    break
                except (ValueError, IndexError):
                    pass

        # Diff 계산
        diff_lines = []
        if before_schema or after_schema:
            before_lines = before_schema.splitlines(keepends=True)
            after_lines = after_schema.splitlines(keepends=True)
            diff = difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile='BEFORE',
                tofile='AFTER',
                lineterm=''
            )
            diff_lines = [line.rstrip('\n\r') for line in diff]

        has_versions = bool(before_schema or after_schema)

        return JsonResponse({
            'success': True,
            'has_versions': has_versions,
            'table_name': table_name,
            'query_text': execution.query_text,
            'before_schema': before_schema,
            'after_schema': after_schema,
            'diff_lines': diff_lines,
            'executed_at': execution.executed_at.strftime('%Y-%m-%d %H:%M:%S'),
            'operator': getattr(execution, 'operator', '')
        })


# ============ Batch Execution Views ============
class BatchExecutionPageView(View):
    """배치 실행 페이지 뷰"""

    def get(self, request):
        connections = DatabaseConnection.objects.filter(is_active=True)
        context = {
            'connections': connections,
        }
        return render(request, 'query_manager/batch_execution.html', context)


class BatchExecutionApiView(View):
    """배치 실행 API"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            connection_id = data.get('connection_id')
            query_text = data.get('query', '').strip()
            batch_size = int(data.get('batch_size', 10))
            sleep_time = float(data.get('sleep_time', 0))
            operator = data.get('operator', '').strip()

            # 입력 검증
            if not connection_id:
                return JsonResponse({'success': False, 'error': '연결을 선택해주세요.'})
            if not query_text:
                return JsonResponse({'success': False, 'error': '쿼리를 입력해주세요.'})
            if not operator:
                return JsonResponse({'success': False, 'error': '작업자를 입력해주세요.'})

            connection = get_object_or_404(DatabaseConnection, pk=connection_id)
            service = QueryService(connection)

            # 쿼리 분리
            queries = service.split_queries(query_text)
            total_queries = len(queries)

            if total_queries == 0:
                return JsonResponse({'success': False, 'error': '실행할 쿼리가 없습니다.'})

            # 배치 ID 생성
            batch_id = str(uuid.uuid4())[:8]

            # 진행 상황 초기화
            batch_progress_store[batch_id] = {
                'status': 'running',
                'total': total_queries,
                'completed': 0,
                'current_batch': 0,
                'total_batches': (total_queries + batch_size - 1) // batch_size,
                'results': [],
                'stopped': False,
                'error': None
            }

            # 배치 실행 (동기 방식 - 간단 구현)
            results = []
            completed = 0
            total_affected = 0

            for i in range(0, total_queries, batch_size):
                # 중지 확인
                if batch_progress_store.get(batch_id, {}).get('stopped'):
                    batch_progress_store[batch_id]['status'] = 'stopped'
                    break

                batch = queries[i:i + batch_size]
                current_batch_num = i // batch_size + 1

                # 진행 상황 업데이트
                batch_progress_store[batch_id]['current_batch'] = current_batch_num

                # 배치 실행
                batch_result = service.execute_batch(batch, operator)

                # 결과 집계
                batch_info = {
                    'batch_num': current_batch_num,
                    'success': batch_result.get('success', False),
                    'query_count': len(batch),
                    'successful': batch_result.get('successful', 0),
                    'affected_rows': sum(r.get('affected_rows', 0) for r in batch_result.get('results', [])),
                    'error': batch_result.get('error')
                }
                results.append(batch_info)
                total_affected += batch_info['affected_rows']

                completed += len(batch)
                batch_progress_store[batch_id]['completed'] = completed
                batch_progress_store[batch_id]['results'] = results

                # 배치 간 대기
                if sleep_time > 0 and i + batch_size < total_queries:
                    time.sleep(sleep_time)

            # 완료 상태 업데이트
            final_status = 'stopped' if batch_progress_store.get(batch_id, {}).get('stopped') else 'completed'
            batch_progress_store[batch_id]['status'] = final_status

            return JsonResponse({
                'success': True,
                'batch_id': batch_id,
                'total_queries': total_queries,
                'completed': completed,
                'total_batches': batch_progress_store[batch_id]['total_batches'],
                'total_affected_rows': total_affected,
                'results': results,
                'status': final_status
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class BatchExecutionProgressView(View):
    """배치 실행 진행 상황 조회 API"""

    def get(self, request, batch_id):
        progress = batch_progress_store.get(batch_id)

        if not progress:
            return JsonResponse({'error': '배치를 찾을 수 없습니다.'}, status=404)

        percent = (progress['completed'] / progress['total'] * 100) if progress['total'] > 0 else 0

        return JsonResponse({
            'status': progress['status'],
            'total': progress['total'],
            'completed': progress['completed'],
            'progress': round(percent, 1),
            'current_batch': progress['current_batch'],
            'total_batches': progress['total_batches'],
            'stopped': progress['stopped'],
            'results': progress['results']
        })


class BatchExecutionStopView(View):
    """배치 실행 중지 API"""

    def post(self, request, batch_id):
        if batch_id in batch_progress_store:
            batch_progress_store[batch_id]['stopped'] = True
            return JsonResponse({'success': True, 'message': '중지 요청됨'})

        return JsonResponse({'success': False, 'error': '배치를 찾을 수 없습니다.'}, status=404)
