from django.db import models


class DatabaseConnection(models.Model):
    """데이터베이스 연결 정보 모델"""
    name = models.CharField(max_length=100, unique=True, verbose_name='연결 이름')
    host = models.CharField(max_length=255, blank=True, default='', verbose_name='호스트')
    port = models.IntegerField(default=3306, verbose_name='포트')
    database = models.CharField(max_length=100, blank=True, default='', verbose_name='데이터베이스명')
    username = models.CharField(max_length=100, verbose_name='사용자명')
    password = models.CharField(max_length=255, verbose_name='비밀번호')
    schema = models.CharField(max_length=100, blank=True, default='', verbose_name='스키마')
    is_active = models.BooleanField(default=True, verbose_name='활성화')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일')

    # 다중 서버 지원
    hosts = models.TextField(
        blank=True,
        default='',
        verbose_name='호스트 목록',
        help_text='여러 호스트를 줄바꿈으로 구분'
    )

    class Meta:
        verbose_name = '데이터베이스 연결'
        verbose_name_plural = '데이터베이스 연결 목록'
        ordering = ['name']

    def __str__(self):
        if self.database:
            return f"{self.name} ({self.host}:{self.port}/{self.database})"
        return f"{self.name} ({self.host}:{self.port})"

    def get_display_name(self):
        """표시용 이름 반환"""
        if self.database:
            return f"{self.host}:{self.port}/{self.database}"
        return f"{self.host}:{self.port}"

    def get_hosts_list(self) -> list:
        """호스트 목록 반환 (다중 서버 지원)"""
        if self.hosts.strip():
            return [h.strip() for h in self.hosts.strip().split('\n') if h.strip()]
        return [self.host] if self.host else []

    def is_multi_server(self) -> bool:
        """다중 서버 여부 확인"""
        return len(self.get_hosts_list()) > 1

    def get_hosts_count(self) -> int:
        """호스트 개수 반환"""
        return len(self.get_hosts_list())


class QueryExecution(models.Model):
    """쿼리 실행 이력 모델"""
    QUERY_TYPE_CHOICES = [
        ('SELECT', 'SELECT'),
        ('INSERT', 'INSERT'),
        ('UPDATE', 'UPDATE'),
        ('DELETE', 'DELETE'),
        ('DDL', 'DDL'),
        ('OTHER', '기타'),
    ]

    STATUS_CHOICES = [
        ('SUCCESS', '성공'),
        ('FAILED', '실패'),
    ]

    connection = models.ForeignKey(
        DatabaseConnection,
        on_delete=models.CASCADE,
        related_name='query_executions',
        verbose_name='연결'
    )
    query_text = models.TextField(verbose_name='쿼리')
    query_type = models.CharField(
        max_length=20,
        choices=QUERY_TYPE_CHOICES,
        default='OTHER',
        verbose_name='쿼리 유형'
    )
    executed_by = models.CharField(max_length=100, blank=True, verbose_name='실행자')
    executed_at = models.DateTimeField(auto_now_add=True, verbose_name='실행 시간')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='SUCCESS',
        verbose_name='상태'
    )
    affected_rows = models.IntegerField(null=True, blank=True, verbose_name='영향받은 행')
    execution_time = models.FloatField(default=0, verbose_name='실행 시간(초)')
    error_message = models.TextField(blank=True, verbose_name='에러 메시지')

    # DDL 쿼리의 경우 스키마 변경 전/후 저장
    schema_before = models.TextField(blank=True, verbose_name='실행 전 스키마')
    schema_after = models.TextField(blank=True, verbose_name='실행 후 스키마')

    # 쿼리 결과 (SELECT의 경우)
    result_data = models.JSONField(null=True, blank=True, verbose_name='결과 데이터')
    result_columns = models.JSONField(null=True, blank=True, verbose_name='결과 컬럼')

    # 검수 워크플로우 지원
    operator = models.CharField(max_length=100, blank=True, verbose_name='작업자')
    validation_result = models.JSONField(null=True, blank=True, verbose_name='검증 결과')

    # 다중 쿼리 배치 지원
    batch_id = models.CharField(max_length=50, blank=True, verbose_name='배치 ID')
    query_index = models.IntegerField(default=0, verbose_name='배치 내 순서')

    class Meta:
        verbose_name = '쿼리 실행 이력'
        verbose_name_plural = '쿼리 실행 이력 목록'
        ordering = ['-executed_at']
        indexes = [
            models.Index(fields=['connection', '-executed_at'], name='query_manag_connect_idx'),
            models.Index(fields=['query_type'], name='query_manag_query_t_idx'),
            models.Index(fields=['status'], name='query_manag_status_idx'),
        ]

    def __str__(self):
        return f"{self.connection.name} - {self.query_type} ({self.status})"

    @classmethod
    def detect_query_type(cls, query: str) -> str:
        """쿼리 유형 자동 감지"""
        query_upper = query.strip().upper()
        if query_upper.startswith('SELECT'):
            return 'SELECT'
        elif query_upper.startswith('INSERT'):
            return 'INSERT'
        elif query_upper.startswith('UPDATE'):
            return 'UPDATE'
        elif query_upper.startswith('DELETE'):
            return 'DELETE'
        elif any(query_upper.startswith(ddl) for ddl in ['CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'RENAME']):
            return 'DDL'
        return 'OTHER'


class SchemaVersion(models.Model):
    """테이블별 스키마 버전 관리 모델"""
    connection = models.ForeignKey(
        DatabaseConnection,
        on_delete=models.CASCADE,
        related_name='schema_versions',
        verbose_name='연결'
    )
    table_name = models.CharField(max_length=255, verbose_name='테이블명')
    version = models.IntegerField(default=1, verbose_name='버전')
    schema_definition = models.TextField(verbose_name='스키마 정의')  # CREATE TABLE 문
    checksum = models.CharField(max_length=64, verbose_name='체크섬')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    query_execution = models.ForeignKey(
        QueryExecution,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='schema_versions',
        verbose_name='관련 쿼리'
    )
    # 추가 필드
    executed_by = models.CharField(max_length=100, blank=True, verbose_name='실행자')
    change_summary = models.TextField(blank=True, verbose_name='변경 요약')
    ddl_type = models.CharField(max_length=50, blank=True, verbose_name='DDL 유형')

    class Meta:
        verbose_name = '스키마 버전'
        verbose_name_plural = '스키마 버전 목록'
        ordering = ['connection', 'table_name', '-version']
        unique_together = ['connection', 'table_name', 'version']
        indexes = [
            models.Index(fields=['connection', 'table_name'], name='query_manag_conn_table_idx'),
        ]

    def __str__(self):
        return f"{self.connection.name} - {self.table_name} v{self.version}"


class SchemaVersionTag(models.Model):
    """스키마 버전 태그/메모 모델"""
    schema_version = models.ForeignKey(
        SchemaVersion,
        on_delete=models.CASCADE,
        related_name='tags',
        verbose_name='스키마 버전'
    )
    tag_name = models.CharField(max_length=100, verbose_name='태그명')
    memo = models.TextField(blank=True, verbose_name='메모')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    created_by = models.CharField(max_length=100, blank=True, verbose_name='작성자')

    class Meta:
        verbose_name = '스키마 버전 태그'
        verbose_name_plural = '스키마 버전 태그 목록'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.schema_version} - {self.tag_name}"
