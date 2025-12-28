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

from .models import DatabaseConnection, QueryExecution, SchemaVersion, SchemaVersionTag
import uuid
import difflib

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

        # DDL인 경우 테이블명 추출
        table_name = None
        if query_type == 'DDL':
            table_name = self._extract_table_name(query)

        try:
            conn = self._get_db_connection()
            try:
                with conn.cursor() as cursor:
                    # DDL 실행 전 스키마 조회 (같은 커서 사용)
                    if query_type == 'DDL' and table_name:
                        result['schema_before'] = self.get_table_schema(table_name, cursor)

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

                    # DDL 실행 후 스키마 조회 (같은 커서 사용)
                    if query_type == 'DDL' and table_name:
                        result['schema_after'] = self.get_table_schema(table_name, cursor)
                        # 스키마 버전 저장
                        if result['schema_after']:
                            self._save_schema_version(table_name, result['schema_after'])

                result['success'] = True
            finally:
                conn.close()

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

    def get_table_schema(self, table_name: str, cursor=None) -> str:
        """
        테이블 스키마(CREATE TABLE) 조회

        Args:
            table_name: 테이블명 (db.table 형식도 지원)
            cursor: 기존 커서 (제공되면 해당 커서 사용, 없으면 새 연결 생성)
        """
        # 테이블명에서 백틱 처리 (db.table 형식 지원)
        if '.' in table_name:
            parts = table_name.split('.', 1)
            escaped_name = f"`{parts[0]}`.`{parts[1]}`"
        else:
            escaped_name = f"`{table_name}`"

        try:
            if cursor:
                # 기존 커서 사용
                cursor.execute(f"SHOW CREATE TABLE {escaped_name}")
                row = cursor.fetchone()
                if row:
                    return row.get('Create Table', '')
            else:
                # 새 연결 생성
                conn = self._get_db_connection()
                try:
                    with conn.cursor() as cur:
                        cur.execute(f"SHOW CREATE TABLE {escaped_name}")
                        row = cur.fetchone()
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
        ALTER 문 분석 및 최적화 제안 (온라인 DDL 분석)

        Returns:
            dict: {
                'is_alter': bool,
                'table_name': str,
                'operation': str,
                'suggestions': list[dict],
                'estimated_impact': str,
                'combined_options': list[str],
                'copyable_queries': list[str]
            }
        """
        result = {
            'is_alter': False,
            'table_name': '',
            'operation': '',
            'suggestions': [],
            'estimated_impact': '',
            'combined_options': [],
            'copyable_queries': [],
        }

        query_upper = query.strip().upper()
        if not query_upper.startswith('ALTER'):
            return result

        result['is_alter'] = True
        result['table_name'] = self._extract_table_name(query)

        # 쿼리에서 기존 ALGORITHM/LOCK 제거
        base_query = query.strip().rstrip(';')
        base_query = re.sub(r'\s*,?\s*ALGORITHM\s*=\s*\w+', '', base_query, flags=re.IGNORECASE)
        base_query = re.sub(r'\s*,?\s*LOCK\s*=\s*\w+', '', base_query, flags=re.IGNORECASE)

        # ALTER 작업 유형 분석
        if 'ADD COLUMN' in query_upper or ('ADD ' in query_upper and 'ADD INDEX' not in query_upper):
            result['operation'] = 'ADD COLUMN'
            result['suggestions'] = [
                {
                    'option': 'ALGORITHM=INSTANT',
                    'combined_option': 'ALGORITHM=INSTANT, LOCK=NONE',
                    'description': 'MySQL 8.0+에서 즉시 메타데이터만 변경 (가장 빠름)',
                    'lock': 'LOCK=NONE',
                    'impact': '매우 낮음',
                },
                {
                    'option': 'ALGORITHM=INPLACE',
                    'combined_option': 'ALGORITHM=INPLACE, LOCK=NONE',
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
                    'combined_option': 'ALGORITHM=INPLACE, LOCK=NONE',
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
                    'combined_option': 'ALGORITHM=INPLACE, LOCK=SHARED',
                    'description': '가능한 경우 인플레이스로 수행',
                    'lock': 'LOCK=SHARED',
                    'impact': '중간',
                },
                {
                    'option': 'ALGORITHM=COPY',
                    'combined_option': 'ALGORITHM=COPY, LOCK=EXCLUSIVE',
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
                    'combined_option': 'ALGORITHM=INPLACE, LOCK=NONE',
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
                    'combined_option': 'ALGORITHM=INPLACE, LOCK=NONE',
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
                    'option': 'ALGORITHM=INPLACE',
                    'combined_option': 'ALGORITHM=INPLACE, LOCK=NONE',
                    'description': '가능한 경우 온라인으로 수행',
                    'lock': 'LOCK=NONE',
                    'impact': '알 수 없음',
                },
            ]
            result['estimated_impact'] = '작업 유형에 따라 다름'

        # combined_options 및 copyable_queries 생성
        for suggestion in result['suggestions']:
            combined = suggestion.get('combined_option', f"{suggestion['option']}, {suggestion['lock']}")
            result['combined_options'].append(combined)
            result['copyable_queries'].append(f"{base_query} {combined};")

        return result

    def _extract_table_name(self, query: str) -> Optional[str]:
        """쿼리에서 테이블명 추출 (db.table 형식 지원)"""
        # 테이블명 패턴: `db`.`table`, db.table, `table`, table
        table_pattern = r'(?:`?(\w+)`?\.)?`?(\w+)`?'

        patterns = [
            rf'ALTER\s+TABLE\s+{table_pattern}',
            rf'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{table_pattern}',
            rf'DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?{table_pattern}',
            rf'TRUNCATE\s+(?:TABLE\s+)?{table_pattern}',
            rf'RENAME\s+TABLE\s+{table_pattern}',
        ]

        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                # group(1)은 db명, group(2)는 테이블명
                # db명이 있으면 db.table 형식으로 반환
                db_name = match.group(1)
                table_name = match.group(2)
                if db_name:
                    return f"{db_name}.{table_name}"
                return table_name
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

    def split_queries(self, query_text: str) -> list:
        """
        세미콜론으로 구분된 쿼리를 분리
        문자열 리터럴 내의 세미콜론은 무시
        """
        queries = []
        current_query = []
        in_string = False
        string_char = None
        i = 0

        while i < len(query_text):
            char = query_text[i]

            # 문자열 시작/종료 체크
            if char in ("'", '"') and (i == 0 or query_text[i-1] != '\\'):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None

            # 세미콜론 처리
            if char == ';' and not in_string:
                query = ''.join(current_query).strip()
                if query:
                    queries.append(query)
                current_query = []
            else:
                current_query.append(char)

            i += 1

        # 마지막 쿼리 처리
        query = ''.join(current_query).strip()
        if query:
            queries.append(query)

        return queries

    def validate_query(self, query: str) -> dict:
        """
        쿼리 문법 및 의미 검증 수행

        Returns:
            dict: {
                'valid': bool,
                'errors': list,
                'warnings': list,
                'query_type': str,
                'affected_tables': list,
                'is_dangerous': bool,
                'danger_reason': str
            }
        """
        result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'query_type': '',
            'affected_tables': [],
            'is_dangerous': False,
            'danger_reason': ''
        }

        query = query.strip()
        if not query:
            result['valid'] = False
            result['errors'].append('쿼리가 비어있습니다.')
            return result

        query_type = QueryExecution.detect_query_type(query)
        result['query_type'] = query_type

        # 테이블명 추출
        table_name = self._extract_table_name(query)
        if table_name:
            result['affected_tables'].append(table_name)

        # DML/DQL에서 테이블명 추출
        if not table_name:
            table_name = self._extract_table_from_dml(query)
            if table_name:
                result['affected_tables'].append(table_name)

        query_upper = query.upper()

        # 위험한 쿼리 체크
        if 'DROP TABLE' in query_upper:
            result['is_dangerous'] = True
            result['danger_reason'] = 'DROP TABLE은 테이블을 완전히 삭제합니다.'
            result['warnings'].append('⚠️ DROP TABLE: 테이블이 완전히 삭제됩니다.')

        if 'TRUNCATE' in query_upper:
            result['is_dangerous'] = True
            result['danger_reason'] = 'TRUNCATE는 모든 데이터를 삭제합니다.'
            result['warnings'].append('⚠️ TRUNCATE: 모든 데이터가 삭제됩니다.')

        if 'DELETE' in query_upper and 'WHERE' not in query_upper:
            result['is_dangerous'] = True
            result['danger_reason'] = 'WHERE 절이 없는 DELETE는 모든 행을 삭제합니다.'
            result['warnings'].append('⚠️ WHERE 절이 없는 DELETE: 모든 행이 삭제됩니다.')

        if 'UPDATE' in query_upper and 'WHERE' not in query_upper:
            result['is_dangerous'] = True
            result['danger_reason'] = 'WHERE 절이 없는 UPDATE는 모든 행을 수정합니다.'
            result['warnings'].append('⚠️ WHERE 절이 없는 UPDATE: 모든 행이 수정됩니다.')

        # 문법 및 의미 검증
        try:
            conn = self._get_db_connection()
            try:
                with conn.cursor() as cursor:
                    if query_type == 'DDL':
                        # DDL 검증: PREPARE 문 사용
                        self._validate_ddl_query(cursor, query, result)
                    elif query_type == 'SELECT':
                        # SELECT 검증: EXPLAIN 사용
                        self._validate_select_query(cursor, query, result)
                    else:
                        # DML 검증: EXPLAIN 사용
                        self._validate_dml_query(cursor, query, result)

                    # 테이블 존재 여부 확인
                    if result['affected_tables'] and result['valid']:
                        self._validate_table_exists(cursor, result['affected_tables'], result)

            finally:
                conn.close()
        except pymysql.Error as e:
            error_msg = str(e)
            error_code = e.args[0] if e.args else 0

            # 연결 오류가 아닌 경우 검증 실패로 처리
            if error_code not in [2003, 2006, 2013]:  # 연결 관련 에러
                result['valid'] = False
                result['errors'].append(f'검증 오류: {self._parse_mysql_error(error_msg)}')
            else:
                result['warnings'].append(f'검증 중 연결 오류: {error_msg}')

        return result

    def _validate_ddl_query(self, cursor, query: str, result: dict):
        """DDL 쿼리 문법 검증"""
        query_upper = query.upper().strip()

        # CREATE TABLE 검증
        if query_upper.startswith('CREATE TABLE'):
            # 임시로 IF NOT EXISTS를 추가해서 검증
            test_query = query
            if 'IF NOT EXISTS' not in query_upper:
                test_query = query.replace('CREATE TABLE', 'CREATE TABLE IF NOT EXISTS', 1)

            # 실제로 실행하지 않고 파싱만 하기 위해 PREPARE 사용
            try:
                stmt_name = f"stmt_{uuid.uuid4().hex[:8]}"
                cursor.execute(f"PREPARE {stmt_name} FROM %s", (test_query,))
                cursor.execute(f"DEALLOCATE PREPARE {stmt_name}")
            except pymysql.Error as e:
                error_msg = str(e)
                result['valid'] = False
                result['errors'].append(f'문법 오류: {self._parse_mysql_error(error_msg)}')

        # ALTER TABLE 검증
        elif query_upper.startswith('ALTER TABLE'):
            try:
                stmt_name = f"stmt_{uuid.uuid4().hex[:8]}"
                cursor.execute(f"PREPARE {stmt_name} FROM %s", (query,))
                cursor.execute(f"DEALLOCATE PREPARE {stmt_name}")
            except pymysql.Error as e:
                error_msg = str(e)
                result['valid'] = False
                result['errors'].append(f'문법 오류: {self._parse_mysql_error(error_msg)}')

        # DROP TABLE 검증
        elif query_upper.startswith('DROP TABLE'):
            # 테이블 존재 여부 확인
            table_name = self._extract_table_name(query)
            if table_name and 'IF EXISTS' not in query_upper:
                try:
                    cursor.execute(f"SHOW TABLES LIKE %s", (table_name,))
                    if not cursor.fetchone():
                        result['valid'] = False
                        result['errors'].append(f"테이블 '{table_name}'이(가) 존재하지 않습니다.")
                except pymysql.Error:
                    pass

        # 기타 DDL
        else:
            try:
                stmt_name = f"stmt_{uuid.uuid4().hex[:8]}"
                cursor.execute(f"PREPARE {stmt_name} FROM %s", (query,))
                cursor.execute(f"DEALLOCATE PREPARE {stmt_name}")
            except pymysql.Error as e:
                error_msg = str(e)
                result['valid'] = False
                result['errors'].append(f'문법 오류: {self._parse_mysql_error(error_msg)}')

    def _validate_select_query(self, cursor, query: str, result: dict):
        """SELECT 쿼리 검증"""
        try:
            cursor.execute(f"EXPLAIN {query}")
        except pymysql.Error as e:
            error_msg = str(e)
            result['valid'] = False
            result['errors'].append(f'쿼리 오류: {self._parse_mysql_error(error_msg)}')

    def _validate_dml_query(self, cursor, query: str, result: dict):
        """DML 쿼리 검증 (INSERT, UPDATE, DELETE)"""
        try:
            # EXPLAIN으로 검증
            cursor.execute(f"EXPLAIN {query}")
        except pymysql.Error as e:
            error_msg = str(e)
            result['valid'] = False
            result['errors'].append(f'쿼리 오류: {self._parse_mysql_error(error_msg)}')

    def _validate_table_exists(self, cursor, tables: list, result: dict):
        """테이블 존재 여부 확인"""
        for table_name in tables:
            try:
                cursor.execute(f"SHOW TABLES LIKE %s", (table_name,))
                if not cursor.fetchone():
                    result['warnings'].append(f"테이블 '{table_name}'이(가) 존재하지 않을 수 있습니다.")
            except pymysql.Error:
                pass

    def _extract_table_from_dml(self, query: str) -> str:
        """DML 쿼리에서 테이블명 추출"""
        patterns = [
            r'FROM\s+`?(\w+)`?',  # SELECT ... FROM table
            r'INTO\s+`?(\w+)`?',  # INSERT INTO table
            r'UPDATE\s+`?(\w+)`?',  # UPDATE table
            r'DELETE\s+FROM\s+`?(\w+)`?',  # DELETE FROM table
        ]

        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1)
        return ''

    def _parse_mysql_error(self, error_msg: str) -> str:
        """MySQL 에러 메시지를 사용자 친화적으로 변환"""
        # 에러 코드별 한글 메시지
        error_mappings = {
            '1064': '문법 오류',
            '1146': '테이블이 존재하지 않습니다',
            '1054': '컬럼이 존재하지 않습니다',
            '1062': '중복된 키 값입니다',
            '1452': '외래 키 제약 조건 위반',
            '1451': '자식 레코드가 존재하여 삭제할 수 없습니다',
            '1366': '데이터 타입이 맞지 않습니다',
            '1406': '데이터가 너무 깁니다',
            '1048': 'NULL 값이 허용되지 않습니다',
            '1136': '컬럼 수가 맞지 않습니다',
            '1364': '필수 필드에 값이 없습니다',
        }

        # 에러 코드 추출
        code_match = re.search(r'\((\d+),', error_msg)
        if code_match:
            error_code = code_match.group(1)
            if error_code in error_mappings:
                # 상세 메시지도 포함
                detail_match = re.search(r"'([^']+)'", error_msg)
                detail = f" ({detail_match.group(1)})" if detail_match else ""
                return f"{error_mappings[error_code]}{detail}"

        # 원본 메시지에서 핵심 내용만 추출
        clean_msg = re.sub(r'^\(\d+,\s*["\']', '', error_msg)
        clean_msg = re.sub(r'["\']?\)$', '', clean_msg)
        return clean_msg[:200]  # 최대 200자

    def execute_batch(self, queries: list, operator: str) -> dict:
        """
        다중 쿼리 배치 실행 - 하나라도 실패 시 전체 롤백

        Returns:
            dict: {
                'batch_id': str,
                'success': bool,
                'total': int,
                'successful': int,
                'failed': int,
                'results': list[dict],
                'error': str
            }
        """
        batch_id = str(uuid.uuid4())[:8]
        result = {
            'batch_id': batch_id,
            'success': False,
            'total': len(queries),
            'successful': 0,
            'failed': 0,
            'results': [],
            'error': ''
        }

        if not queries:
            result['error'] = '실행할 쿼리가 없습니다.'
            return result

        if not operator:
            result['error'] = '작업자를 입력해주세요.'
            return result

        try:
            conn = self._get_db_connection()
            conn.autocommit(False)  # 트랜잭션 시작

            try:
                query_results = []

                for idx, query in enumerate(queries):
                    query = query.strip()
                    if not query:
                        continue

                    query_type = QueryExecution.detect_query_type(query)
                    start_time = time.time()

                    query_result = {
                        'index': idx,
                        'query': query[:100] + '...' if len(query) > 100 else query,
                        'query_type': query_type,
                        'success': False,
                        'affected_rows': 0,
                        'execution_time': 0,
                        'error': '',
                        'schema_before': '',
                        'schema_after': ''
                    }

                    # DDL인 경우 스키마 저장
                    table_name = None
                    if query_type == 'DDL':
                        table_name = self._extract_table_name(query)

                    try:
                        with conn.cursor() as cursor:
                            # DDL 실행 전 스키마 조회 (같은 커서 사용)
                            if query_type == 'DDL' and table_name:
                                query_result['schema_before'] = self.get_table_schema(table_name, cursor)

                            cursor.execute(query)

                            if query_type == 'SELECT':
                                rows = cursor.fetchmany(self.max_rows)
                                query_result['affected_rows'] = len(rows)
                            else:
                                query_result['affected_rows'] = cursor.rowcount

                            # DDL 실행 후 스키마 조회 (같은 커서 사용)
                            if query_type == 'DDL' and table_name:
                                query_result['schema_after'] = self.get_table_schema(table_name, cursor)

                        query_result['success'] = True
                        query_result['execution_time'] = time.time() - start_time

                    except pymysql.Error as e:
                        query_result['error'] = str(e)
                        query_result['execution_time'] = time.time() - start_time
                        query_results.append(query_result)

                        # 트랜잭션 롤백
                        conn.rollback()
                        result['results'] = query_results
                        result['failed'] = 1
                        result['successful'] = idx
                        result['error'] = f'쿼리 {idx+1} 실행 실패로 전체 롤백: {e}'

                        # 실행 이력 저장 (실패)
                        for qr in query_results:
                            QueryExecution.objects.create(
                                connection=self.connection,
                                query_text=queries[qr['index']],
                                query_type=qr['query_type'],
                                executed_by='',
                                operator=operator,
                                status='FAILED' if qr.get('error') else 'SUCCESS',
                                affected_rows=qr['affected_rows'],
                                execution_time=qr['execution_time'],
                                error_message=qr.get('error', '') or '배치 롤백됨',
                                schema_before=qr.get('schema_before', ''),
                                schema_after=qr.get('schema_after', ''),
                                batch_id=batch_id,
                                query_index=qr['index']
                            )

                        return result

                    query_results.append(query_result)

                # 모든 쿼리 성공 - 커밋
                conn.commit()
                result['success'] = True
                result['successful'] = len(query_results)
                result['results'] = query_results

                # 실행 이력 저장 (성공)
                for qr in query_results:
                    execution = QueryExecution.objects.create(
                        connection=self.connection,
                        query_text=queries[qr['index']],
                        query_type=qr['query_type'],
                        executed_by='',
                        operator=operator,
                        status='SUCCESS',
                        affected_rows=qr['affected_rows'],
                        execution_time=qr['execution_time'],
                        error_message='',
                        schema_before=qr.get('schema_before', ''),
                        schema_after=qr.get('schema_after', ''),
                        batch_id=batch_id,
                        query_index=qr['index']
                    )

                    # DDL인 경우 스키마 버전 저장
                    if qr['query_type'] == 'DDL' and qr.get('schema_after'):
                        table_name = self._extract_table_name(queries[qr['index']])
                        if table_name:
                            self._save_schema_version(
                                table_name,
                                qr['schema_after'],
                                executed_by=operator,
                                ddl_type=self._extract_ddl_type(queries[qr['index']]),
                                old_schema=qr.get('schema_before', ''),
                                query_execution=execution
                            )

            finally:
                conn.close()

        except pymysql.Error as e:
            result['error'] = f'연결 오류: {e}'
            logger.error(f"Batch execution connection error: {e}")

        return result

    def _extract_ddl_type(self, query: str) -> str:
        """DDL 유형 추출 (CREATE, ALTER, DROP 등)"""
        query_upper = query.strip().upper()
        if query_upper.startswith('CREATE'):
            return 'CREATE'
        elif query_upper.startswith('ALTER'):
            return 'ALTER'
        elif query_upper.startswith('DROP'):
            return 'DROP'
        elif query_upper.startswith('TRUNCATE'):
            return 'TRUNCATE'
        elif query_upper.startswith('RENAME'):
            return 'RENAME'
        return 'OTHER'

    def _save_schema_version(self, table_name: str, schema_definition: str,
                            executed_by: str = '', ddl_type: str = '',
                            old_schema: str = '', query_execution=None):
        """스키마 버전 저장 (확장)"""
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

        # 변경 요약 생성
        change_summary = self.generate_change_summary(old_schema, schema_definition)

        SchemaVersion.objects.create(
            connection=self.connection,
            table_name=table_name,
            version=new_version,
            schema_definition=schema_definition,
            checksum=checksum,
            executed_by=executed_by,
            change_summary=change_summary,
            ddl_type=ddl_type,
            query_execution=query_execution
        )

    def generate_change_summary(self, old_schema: str, new_schema: str) -> str:
        """DDL 변경 요약 자동 생성"""
        if not old_schema:
            return '테이블 생성'

        if not new_schema:
            return '테이블 삭제'

        changes = []

        # 컬럼 변경 분석
        old_columns = self._extract_columns(old_schema)
        new_columns = self._extract_columns(new_schema)

        added = set(new_columns.keys()) - set(old_columns.keys())
        removed = set(old_columns.keys()) - set(new_columns.keys())

        for col in added:
            changes.append(f"컬럼 추가: {col}")
        for col in removed:
            changes.append(f"컬럼 삭제: {col}")

        # 인덱스 변경 분석
        old_indexes = self._extract_indexes(old_schema)
        new_indexes = self._extract_indexes(new_schema)

        added_idx = set(new_indexes) - set(old_indexes)
        removed_idx = set(old_indexes) - set(new_indexes)

        for idx in added_idx:
            changes.append(f"인덱스 추가: {idx}")
        for idx in removed_idx:
            changes.append(f"인덱스 삭제: {idx}")

        return '; '.join(changes) if changes else '스키마 변경'

    def _extract_columns(self, schema: str) -> dict:
        """스키마에서 컬럼 추출"""
        columns = {}
        # 간단한 컬럼 추출 정규식
        pattern = r'`(\w+)`\s+(\w+(?:\([^)]+\))?)'
        for match in re.finditer(pattern, schema):
            col_name, col_type = match.groups()
            columns[col_name] = col_type
        return columns

    def _extract_indexes(self, schema: str) -> list:
        """스키마에서 인덱스 추출"""
        indexes = []
        # KEY, INDEX, UNIQUE 패턴 매칭
        patterns = [
            r'(?:PRIMARY\s+)?KEY\s+`?(\w+)`?',
            r'(?:UNIQUE\s+)?INDEX\s+`?(\w+)`?',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, schema, re.IGNORECASE):
                indexes.append(match.group(1))
        return indexes

    def compare_schema_versions(self, version1_id: int, version2_id: int) -> dict:
        """
        두 스키마 버전 상세 비교

        Returns:
            dict: {
                'table_name': str,
                'version1': {...},
                'version2': {...},
                'diff_lines': list,
                'added_columns': list,
                'removed_columns': list,
                'added_indexes': list,
                'removed_indexes': list
            }
        """
        result = {
            'table_name': '',
            'version1': None,
            'version2': None,
            'diff_lines': [],
            'added_columns': [],
            'removed_columns': [],
            'added_indexes': [],
            'removed_indexes': []
        }

        try:
            v1 = SchemaVersion.objects.get(pk=version1_id)
            v2 = SchemaVersion.objects.get(pk=version2_id)
        except SchemaVersion.DoesNotExist:
            return {'error': '버전을 찾을 수 없습니다.'}

        result['table_name'] = v1.table_name
        result['version1'] = {
            'id': v1.id,
            'version': v1.version,
            'schema': v1.schema_definition,
            'created_at': v1.created_at.isoformat(),
            'executed_by': v1.executed_by
        }
        result['version2'] = {
            'id': v2.id,
            'version': v2.version,
            'schema': v2.schema_definition,
            'created_at': v2.created_at.isoformat(),
            'executed_by': v2.executed_by
        }

        # JavaScript 호환성을 위한 추가 필드
        result['before_schema'] = v1.schema_definition
        result['after_schema'] = v2.schema_definition

        # 라인별 diff 생성
        lines1 = v1.schema_definition.splitlines()
        lines2 = v2.schema_definition.splitlines()

        diff = difflib.unified_diff(lines1, lines2, lineterm='')
        result['diff_lines'] = list(diff)

        # 컬럼 비교
        cols1 = self._extract_columns(v1.schema_definition)
        cols2 = self._extract_columns(v2.schema_definition)

        result['added_columns'] = list(set(cols2.keys()) - set(cols1.keys()))
        result['removed_columns'] = list(set(cols1.keys()) - set(cols2.keys()))

        # 인덱스 비교
        idx1 = self._extract_indexes(v1.schema_definition)
        idx2 = self._extract_indexes(v2.schema_definition)

        result['added_indexes'] = list(set(idx2) - set(idx1))
        result['removed_indexes'] = list(set(idx1) - set(idx2))

        return result

    def generate_rollback_ddl(self, from_version_id: int, to_version_id: int) -> dict:
        """
        롤백 DDL 생성 (생성만, 실행 안 함)

        Args:
            from_version_id: 현재 버전 ID
            to_version_id: 롤백 대상 버전 ID

        Returns:
            dict: {
                'success': bool,
                'rollback_ddl': str,
                'from_version': int,
                'to_version': int,
                'changes': list,
                'warnings': list
            }
        """
        result = {
            'success': False,
            'rollback_ddl': '',
            'from_version': 0,
            'to_version': 0,
            'changes': [],
            'warnings': []
        }

        try:
            from_ver = SchemaVersion.objects.get(pk=from_version_id)
            to_ver = SchemaVersion.objects.get(pk=to_version_id)
        except SchemaVersion.DoesNotExist:
            result['warnings'].append('버전을 찾을 수 없습니다.')
            return result

        result['from_version'] = from_ver.version
        result['to_version'] = to_ver.version

        # 스키마 비교
        from_cols = self._extract_columns(from_ver.schema_definition)
        to_cols = self._extract_columns(to_ver.schema_definition)

        table_name = from_ver.table_name
        alter_statements = []

        # 추가된 컬럼 삭제 (롤백)
        added_cols = set(from_cols.keys()) - set(to_cols.keys())
        for col in added_cols:
            alter_statements.append(f"DROP COLUMN `{col}`")
            result['changes'].append(f"컬럼 삭제: {col}")

        # 삭제된 컬럼 추가 (롤백) - 타입 정보 필요
        removed_cols = set(to_cols.keys()) - set(from_cols.keys())
        for col in removed_cols:
            col_type = to_cols.get(col, 'VARCHAR(255)')
            alter_statements.append(f"ADD COLUMN `{col}` {col_type}")
            result['changes'].append(f"컬럼 추가: {col} {col_type}")

        # 인덱스 비교
        from_idx = self._extract_indexes(from_ver.schema_definition)
        to_idx = self._extract_indexes(to_ver.schema_definition)

        added_idx = set(from_idx) - set(to_idx)
        for idx in added_idx:
            if idx != 'PRIMARY':
                alter_statements.append(f"DROP INDEX `{idx}`")
                result['changes'].append(f"인덱스 삭제: {idx}")

        if alter_statements:
            result['rollback_ddl'] = f"ALTER TABLE `{table_name}` " + ",\n  ".join(alter_statements) + ";"
            result['success'] = True
        else:
            result['warnings'].append('롤백할 변경사항이 없습니다.')
            result['rollback_ddl'] = f"-- {table_name}: 변경사항 없음"
            result['success'] = True

        result['warnings'].append('⚠️ 자동 생성된 DDL은 검토 후 실행하세요.')
        result['warnings'].append('⚠️ 데이터 손실이 발생할 수 있습니다.')

        return result

    def get_tables_with_database(self, database: str) -> list:
        """특정 데이터베이스의 테이블 목록 조회"""
        tables = []
        try:
            conn = self._get_db_connection(database=database)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SHOW TABLES")
                    for row in cursor.fetchall():
                        table_name = list(row.values())[0]
                        tables.append(table_name)
            finally:
                conn.close()
        except pymysql.Error as e:
            logger.error(f"Failed to get tables for {database}: {e}")
        return tables
