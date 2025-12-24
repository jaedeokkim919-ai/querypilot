from django.db import models


class DatabaseConnection(models.Model):
    """데이터베이스 연결 정보 모델"""
    name = models.CharField(max_length=100, unique=True, verbose_name='연결 이름')
    host = models.CharField(max_length=255, verbose_name='호스트')
    port = models.IntegerField(default=3306, verbose_name='포트')
    database = models.CharField(max_length=100, blank=True, default='', verbose_name='데이터베이스명')
    username = models.CharField(max_length=100, verbose_name='사용자명')
    password = models.CharField(max_length=255, verbose_name='비밀번호')
    schema = models.CharField(max_length=100, blank=True, default='', verbose_name='스키마')
    is_active = models.BooleanField(default=True, verbose_name='활성화')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일')

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

    class Meta:
        verbose_name = '쿼리 실행 이력'
        verbose_name_plural = '쿼리 실행 이력 목록'
        ordering = ['-executed_at']
        indexes = [
            models.Index(fields=['connection', '-executed_at']),
            models.Index(fields=['query_type']),
            models.Index(fields=['status']),
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

    class Meta:
        verbose_name = '스키마 버전'
        verbose_name_plural = '스키마 버전 목록'
        ordering = ['connection', 'table_name', '-version']
        unique_together = ['connection', 'table_name', 'version']
        indexes = [
            models.Index(fields=['connection', 'table_name']),
        ]

    def __str__(self):
        return f"{self.connection.name} - {self.table_name} v{self.version}"
