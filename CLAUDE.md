# CLAUDE.md

이 파일은 Claude Code가 QueryPilot 프로젝트를 이해하고 작업할 때 참조하는 가이드입니다.

## 프로젝트 개요

QueryPilot은 Django 3.2 기반의 다중 데이터베이스 쿼리 관리 및 스키마 버전 관리 웹 애플리케이션입니다. MySQL/MariaDB 데이터베이스를 대상으로 쿼리 실행, 히스토리 추적, 스키마 변경 관리 기능을 제공합니다.

## 핵심 아키텍처

### 디렉토리 구조
- `querypilot/`: Django 프로젝트 설정 (settings.py, urls.py, wsgi.py)
- `query_manager/`: 메인 Django 앱 (모든 비즈니스 로직)
- `static/`: 정적 파일
- `logs/`: 애플리케이션 로그

### 주요 파일
- `query_manager/models.py`: DatabaseConnection, QueryExecution, SchemaVersion, SchemaVersionTag 모델
- `query_manager/views.py`: 20개 이상의 뷰 클래스 (대시보드, 연결관리, 쿼리에디터, 히스토리, 버전관리)
- `query_manager/services.py`: QueryService 클래스 (핵심 비즈니스 로직)
- `query_manager/forms.py`: Django 폼 (연결, 쿼리, 필터링)
- `query_manager/urls.py`: URL 라우팅

### 서비스 레이어
`QueryService` 클래스가 모든 데이터베이스 작업을 처리:
- PyMySQL을 통한 데이터베이스 연결
- 쿼리 실행 (타임아웃, 행 제한 지원)
- 쿼리 검증 (문법 + Semantic 분석)
- 배치 쿼리 실행 (트랜잭션 롤백 지원)
- 스키마 버전 관리
- DDL 전/후 스키마 비교
- ALTER 문 최적화 분석 (온라인 DDL 옵션)

## 주요 기능

### 쿼리 에디터
- CodeMirror 기반 SQL 에디터
- 연결 테스트 및 테이블 목록 조회
- 검수/실행 2단계 워크플로우
- 다중 쿼리 배치 실행 (세미콜론 구분)
- 작업자(operator) 필수 입력

### 쿼리 검증
- **문법 검증**: EXPLAIN/PREPARE를 통한 SQL 문법 검사
- **Semantic 분석**:
  - INSERT: 컬럼 존재 여부, NOT NULL 제약조건 체크
  - UPDATE: SET/WHERE 절 컬럼 존재 여부 체크
  - DELETE: 외래키 참조 체크

### DDL 관리
- DDL 실행 시 스키마 전/후 자동 저장
- 실행 이력에서 전/후 비교 (Side-by-Side, DIFF)
- 온라인 DDL 분석 (ALGORITHM, LOCK 옵션 제안)

### 실행 이력
- 쿼리 유형별 필터 (DDL, DML, DQL)
- 카테고리별 필터
- 작업자별 검색
- DDL 쿼리의 스키마 전/후 비교

## 개발 명령어

```bash
# 개발 서버 실행
python manage.py runserver

# 마이그레이션 생성
python manage.py makemigrations

# 마이그레이션 적용
python manage.py migrate

# 관리자 계정 생성
python manage.py createsuperuser

# 프로덕션 서버 실행
gunicorn -c gunicorn_config.py querypilot.wsgi
```

## 코딩 컨벤션

### Python/Django
- Django 3.2 호환 코드 작성 (Django 4.0 미만)
- 클래스 기반 뷰(CBV) 사용 선호
- 비즈니스 로직은 `services.py`에 분리
- 모델 변경 시 마이그레이션 생성 필수

### 템플릿
- `base.html`을 상속받아 작성
- Bootstrap 5.3 클래스 사용
- Bootstrap Icons 아이콘 사용
- CodeMirror 5.x를 SQL 에디터에 사용

### 데이터베이스
- 관리 DB: Django ORM 사용
- 대상 DB: PyMySQL 직접 연결
- 모든 쿼리 실행은 QueryExecution에 기록
- DDL 실행 시 동일 커서로 스키마 조회 (트랜잭션 일관성)

### JavaScript
- 이벤트 바인딩: `data-*` 속성 + `addEventListener` 패턴 사용
- 인라인 `onclick` 대신 이벤트 위임 선호

## 모델 관계

```
DatabaseConnection (1) ──> (N) QueryExecution
DatabaseConnection (1) ──> (N) SchemaVersion
QueryExecution (1) ──> (N) SchemaVersion
SchemaVersion (1) ──> (N) SchemaVersionTag
```

### QueryExecution 주요 필드
- `operator`: 작업자 (UI 입력)
- `executed_by`: 실행자 (operator와 동기화)
- `schema_before`, `schema_after`: DDL 전/후 스키마
- `batch_id`, `query_index`: 배치 실행 지원
- `validation_result`: 검증 결과 (JSON)

## 환경 변수

필수 환경 변수 (`.env` 파일):
- `DJANGO_SECRET_KEY`: Django 시크릿 키
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`: 관리 DB 설정

선택적 환경 변수:
- `DJANGO_DEBUG`: 디버그 모드 (기본: False)
- `MAX_QUERY_RESULT_ROWS`: 결과 행 제한 (기본: 1000)
- `QUERY_TIMEOUT`: 쿼리 타임아웃 초 (기본: 300)
- `ENABLE_SCHEMA_DIFF`: 스키마 비교 활성화 (기본: True)

## API 엔드포인트

### 쿼리 관련
- `POST /query/execute/`: 단일 쿼리 실행
- `POST /query/review/`: 쿼리 검수 (검증만)
- `POST /query/batch-execute/`: 배치 쿼리 실행
- `POST /query/analyze-alter/`: ALTER 문 분석

### 히스토리 관련
- `GET /history/`: 실행 이력 목록
- `GET /history/<pk>/`: 실행 이력 상세
- `GET /history/<pk>/schema-compare/`: DDL 스키마 비교

### 연결 관련
- `POST /api/connections/<pk>/test/`: 연결 테스트
- `GET /api/connections/<pk>/databases/`: 데이터베이스 목록
- `GET /api/connections/<pk>/tables/`: 테이블 목록
- `GET /api/connections/<pk>/databases/<db>/tables/`: 특정 DB 테이블 목록

## 테스트

현재 테스트 코드 없음. 테스트 추가 시:
```bash
python manage.py test query_manager
```

## 주의사항

1. **보안**: 데이터베이스 비밀번호가 평문으로 저장됨 - 프로덕션에서는 암호화 고려
2. **호환성**: MySQL/MariaDB만 지원 (PostgreSQL, SQLite 미지원)
3. **언어**: UI와 코드 주석이 한국어로 작성됨
4. **타임존**: Asia/Seoul로 설정됨
5. **Django 버전**: 3.2 이상, 4.0 미만 필수
6. **트랜잭션**: 배치 실행 시 하나라도 실패하면 전체 롤백

## 자주 수정되는 영역

- `query_manager/views.py`: 새로운 기능 추가 시
- `query_manager/services.py`: 쿼리 처리 로직 변경 시
- `query_manager/models.py`: 데이터 구조 변경 시
- `query_manager/templates/`: UI 수정 시

## 확장 포인트

1. **새 데이터베이스 지원**: `services.py`의 연결 로직 수정
2. **새 쿼리 유형**: `models.py`의 QUERY_TYPES에 추가
3. **새 API**: `views.py`에 뷰 추가, `urls.py`에 라우팅 추가
4. **새 분석 기능**: `services.py`의 `analyze_alter_statement` 확장
5. **Semantic 분석 확장**: `_semantic_analysis()` 메서드 수정
