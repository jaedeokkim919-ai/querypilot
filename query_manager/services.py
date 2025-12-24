"""
QueryPilot 서비스 클래스
쿼리 실행, 연결 테스트, 스키마 조회, ALTER 분석 등
"""

import re
import time
import hashlib
import logging
from typing import Optional
from django.conf import settings
from django.utils import timezone

import pymysql
from pymysql.cursors import DictCursor

from .models import DatabaseConnection, QueryExecution, SchemaVersion

logger = logging.getLogger(__name__)


class QueryService:
    """쿼리 실행 및 DB 관리 서비스"""

    def __init__(self, connection: DatabaseConnection):
        self.connection = connection
        self.config = getattr(settings, 'QUERYPILOT_CONFIG', {})
        self.max_rows = self.config.get('MAX_QUERY_RESULT_ROWS', 1000)
        self.timeout = self.config.get('QUERY_TIMEOUT', 300)

    def _get_db_connection(self, database: str = None):
        """PyMySQL 연결 생성"""
        connect_params = {
            'host': self.connection.host,
            'port': self.connection.port,
            'user': self.connection.username,
            'password': self.connection.password,
            'charset': 'utf8mb4',
            'connect_timeout': 10,
            'read_timeout': self.timeout,
            'write_timeout': self.timeout,
            'cursorclass': DictCursor,
        }

        # 데이터베이스 지정
        db_name = database or self.connection.database
        if db_name:
            connect_params['database'] = db_name

        return pymysql.connect(**connect_params)

    def test_connection(self) -> dict:
        """연결 테스트"""
        result = {
            'success': False,
            'message': '',
            'server_info': None,
            'databases': [],
        }

        try:
            conn = self._get_db_connection()
            try:
                with conn.cursor() as cursor:
                    # 서버 정보 조회
                    cursor.execute("SELECT VERSION() as version")
                    row = cursor.fetchone()
                    result['server_info'] = {
                        'version': row['version'] if row else 'Unknown'
                    }

                    # 데이터베이스 목록 조회
                    cursor.execute("SHOW DATABASES")
                    result['databases'] = [r['Database'] for r in cursor.fetchall()]

                result['success'] = True
                result['message'] = '연결 성공'
            finally:
                conn.close()
        except pymysql.Error as e:
            result['message'] = f'연결 실패: {e}'
            logger.error(f"Connection test failed for {self.connection.name}: {e}")

        return result

    def execute_query(self, query: str, executed_by: str = '') -> dict:
        """
        쿼리 실행 및 결과 반환

        Returns:
            dict: {
                'success': bool,
                'query_type': str,
                'affected_rows': int,
                'execution_time': float,
                'columns': list,
                'data': list,
                'error': str,
                'execution_id': int
            }
        """
        query = query.strip()
        if not query:
            return {'success': False, 'error': '쿼리가 비어있습니다.'}

        query_type = QueryExecution.detect_query_type(query)
        start_time = time.time()

        result = {
            'success': False,
            'query_type': query_type,
            'affected_rows': 0,
            'execution_time': 0,
            'columns': [],
            'data': [],
            'error': '',
            'execution_id': None,
            'schema_before': '',
            'schema_after': '',
        }

        # DDL인 경우 실행 전 스키마 저장
        table_name = None
        if query_type == 'DDL':
            table_name = self._extract_table_name(query)
            if table_name:
                result['schema_before'] = self.get_table_schema(table_name)

        try:
            conn = self._get_db_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query)

                    if query_type == 'SELECT':
                        # SELECT 결과 가져오기
                        rows = cursor.fetchmany(self.max_rows)
                        result['data'] = rows
                        result['columns'] = [desc[0] for desc in cursor.description] if cursor.description else []
                        result['affected_rows'] = len(rows)
                    else:
                        # DML/DDL 결과
                        result['affected_rows'] = cursor.rowcount
                        conn.commit()

                result['success'] = True
            finally:
                conn.close()

            # DDL인 경우 실행 후 스키마 저장
            if query_type == 'DDL' and table_name:
                result['schema_after'] = self.get_table_schema(table_name)
                # 스키마 버전 저장
                if result['schema_after']:
                    self._save_schema_version(table_name, result['schema_after'])

        except pymysql.Error as e:
            result['error'] = str(e)
            logger.error(f"Query execution failed: {e}")

        result['execution_time'] = time.time() - start_time

        # 실행 이력 저장
        execution = QueryExecution.objects.create(
            connection=self.connection,
            query_text=query,
            query_type=query_type,
            executed_by=executed_by,
            status='SUCCESS' if result['success'] else 'FAILED',
            affected_rows=result['affected_rows'],
            execution_time=result['execution_time'],
            error_message=result['error'],
            schema_before=result.get('schema_before', ''),
            schema_after=result.get('schema_after', ''),
            result_columns=result['columns'] if query_type == 'SELECT' else None,
            result_data=result['data'][:100] if query_type == 'SELECT' else None,  # 최대 100개만 저장
        )
        result['execution_id'] = execution.id

        return result

    def get_table_schema(self, table_name: str) -> str:
        """테이블 스키마(CREATE TABLE) 조회"""
        try:
            conn = self._get_db_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(f"SHOW CREATE TABLE `{table_name}`")
                    row = cursor.fetchone()
                    if row:
                        return row.get('Create Table', '')
            finally:
                conn.close()
        except pymysql.Error as e:
            logger.warning(f"Failed to get schema for {table_name}: {e}")
        return ''

    def get_all_tables(self) -> list:
        """모든 테이블 목록 조회"""
        tables = []
        try:
            conn = self._get_db_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SHOW TABLES")
                    # 결과 컬럼명은 'Tables_in_<database>'
                    for row in cursor.fetchall():
                        table_name = list(row.values())[0]
                        tables.append(table_name)
            finally:
                conn.close()
        except pymysql.Error as e:
            logger.error(f"Failed to get tables: {e}")
        return tables

    def get_databases(self) -> list:
        """데이터베이스 목록 조회"""
        databases = []
        try:
            conn = self._get_db_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SHOW DATABASES")
                    databases = [r['Database'] for r in cursor.fetchall()]
            finally:
                conn.close()
        except pymysql.Error as e:
            logger.error(f"Failed to get databases: {e}")
        return databases

    def analyze_alter_statement(self, query: str) -> dict:
        """
        ALTER 문 분석 및 최적화 제안

        Returns:
            dict: {
                'is_alter': bool,
                'table_name': str,
                'operation': str,
                'suggestions': list[dict],
                'estimated_impact': str
            }
        """
        result = {
            'is_alter': False,
            'table_name': '',
            'operation': '',
            'suggestions': [],
            'estimated_impact': '',
        }

        query_upper = query.strip().upper()
        if not query_upper.startswith('ALTER'):
            return result

        result['is_alter'] = True
        result['table_name'] = self._extract_table_name(query)

        # ALTER 작업 유형 분석
        if 'ADD COLUMN' in query_upper or 'ADD ' in query_upper:
            result['operation'] = 'ADD COLUMN'
            result['suggestions'] = [
                {
                    'option': 'ALGORITHM=INSTANT',
                    'description': 'MySQL 8.0+에서 즉시 메타데이터만 변경 (가장 빠름)',
                    'lock': 'LOCK=NONE',
                    'impact': '매우 낮음',
                },
                {
                    'option': 'ALGORITHM=INPLACE',
                    'description': '테이블 복사 없이 인덱스만 재구성',
                    'lock': 'LOCK=NONE',
                    'impact': '낮음',
                },
            ]
            result['estimated_impact'] = '일반적으로 빠른 작업, INSTANT 지원 시 즉시 완료'

        elif 'DROP COLUMN' in query_upper:
            result['operation'] = 'DROP COLUMN'
            result['suggestions'] = [
                {
                    'option': 'ALGORITHM=INPLACE',
                    'description': '테이블 복사 없이 수행',
                    'lock': 'LOCK=NONE',
                    'impact': '낮음',
                },
            ]
            result['estimated_impact'] = '중간 크기 테이블도 비교적 빠름'

        elif 'MODIFY COLUMN' in query_upper or 'CHANGE COLUMN' in query_upper:
            result['operation'] = 'MODIFY COLUMN'
            result['suggestions'] = [
                {
                    'option': 'ALGORITHM=INPLACE',
                    'description': '가능한 경우 인플레이스로 수행',
                    'lock': 'LOCK=SHARED',
                    'impact': '중간',
                },
                {
                    'option': 'ALGORITHM=COPY',
                    'description': '테이블 전체 복사 (데이터 타입 변경 시)',
                    'lock': 'LOCK=EXCLUSIVE',
                    'impact': '높음',
                },
            ]
            result['estimated_impact'] = '컬럼 타입에 따라 다름, 대용량 테이블은 주의 필요'

        elif 'ADD INDEX' in query_upper or 'CREATE INDEX' in query_upper:
            result['operation'] = 'ADD INDEX'
            result['suggestions'] = [
                {
                    'option': 'ALGORITHM=INPLACE',
                    'description': '온라인 인덱스 생성',
                    'lock': 'LOCK=NONE',
                    'impact': '중간',
                },
            ]
            result['estimated_impact'] = '테이블 크기에 비례, 대용량 테이블은 시간 소요'

        elif 'DROP INDEX' in query_upper:
            result['operation'] = 'DROP INDEX'
            result['suggestions'] = [
                {
                    'option': 'ALGORITHM=INPLACE',
                    'description': '즉시 삭제',
                    'lock': 'LOCK=NONE',
                    'impact': '매우 낮음',
                },
            ]
            result['estimated_impact'] = '거의 즉시 완료'

        else:
            result['operation'] = 'OTHER'
            result['suggestions'] = [
                {
                    'option': 'ALGORITHM=INPLACE, LOCK=NONE',
                    'description': '가능한 경우 온라인으로 수행',
                    'lock': 'LOCK=NONE',
                    'impact': '알 수 없음',
                },
            ]
            result['estimated_impact'] = '작업 유형에 따라 다름'

        return result

    def _extract_table_name(self, query: str) -> Optional[str]:
        """쿼리에서 테이블명 추출"""
        patterns = [
            r'ALTER\s+TABLE\s+`?(\w+)`?',
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?',
            r'DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?`?(\w+)`?',
            r'TRUNCATE\s+(?:TABLE\s+)?`?(\w+)`?',
            r'RENAME\s+TABLE\s+`?(\w+)`?',
        ]

        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _save_schema_version(self, table_name: str, schema_definition: str):
        """스키마 버전 저장"""
        checksum = hashlib.md5(schema_definition.encode()).hexdigest()

        # 기존 최신 버전 조회
        latest = SchemaVersion.objects.filter(
            connection=self.connection,
            table_name=table_name
        ).order_by('-version').first()

        # 체크섬이 같으면 저장하지 않음
        if latest and latest.checksum == checksum:
            return

        new_version = (latest.version + 1) if latest else 1

        SchemaVersion.objects.create(
            connection=self.connection,
            table_name=table_name,
            version=new_version,
            schema_definition=schema_definition,
            checksum=checksum,
        )

    def get_schema_diff(self, table_name: str, version1: int = None, version2: int = None) -> dict:
        """
        스키마 버전 간 Diff 조회

        Args:
            table_name: 테이블명
            version1: 비교 기준 버전 (None이면 이전 버전)
            version2: 비교 대상 버전 (None이면 최신 버전)
        """
        versions = SchemaVersion.objects.filter(
            connection=self.connection,
            table_name=table_name
        ).order_by('-version')

        if not versions.exists():
            return {'error': '스키마 버전이 없습니다.'}

        if version2 is None:
            v2 = versions.first()
        else:
            v2 = versions.filter(version=version2).first()

        if version1 is None:
            v1 = versions.filter(version__lt=v2.version).first() if v2 else None
        else:
            v1 = versions.filter(version=version1).first()

        return {
            'table_name': table_name,
            'version1': {
                'version': v1.version if v1 else None,
                'schema': v1.schema_definition if v1 else '',
                'created_at': v1.created_at.isoformat() if v1 else None,
            },
            'version2': {
                'version': v2.version if v2 else None,
                'schema': v2.schema_definition if v2 else '',
                'created_at': v2.created_at.isoformat() if v2 else None,
            },
        }
