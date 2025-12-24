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
- `query_manager/models.py`: DatabaseConnection, QueryExecution, SchemaVersion 모델
- `query_manager/views.py`: 15개 이상의 뷰 클래스 (대시보드, 연결관리, 쿼리에디터, 히스토리)
- `query_manager/services.py`: QueryService 클래스 (핵심 비즈니스 로직)
- `query_manager/forms.py`: Django 폼 (연결, 쿼리, 필터링)
- `query_manager/urls.py`: URL 라우팅

### 서비스 레이어
`QueryService` 클래스가 모든 데이터베이스 작업을 처리:
- PyMySQL을 통한 데이터베이스 연결
- 쿼리 실행 (타임아웃, 행 제한 지원)
- 스키마 버전 관리
- ALTER 문 최적화 분석

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
- Bootstrap 클래스 사용
- Bootstrap Icons 아이콘 사용
- CodeMirror를 SQL 에디터에 사용

### 데이터베이스
- 관리 DB: Django ORM 사용
- 대상 DB: PyMySQL 직접 연결
- 모든 쿼리 실행은 QueryExecution에 기록

## 모델 관계

```
DatabaseConnection (1) ──> (N) QueryExecution
DatabaseConnection (1) ──> (N) SchemaVersion
QueryExecution (1) ──> (N) SchemaVersion
```

## 환경 변수

필수 환경 변수 (`.env` 파일):
- `DJANGO_SECRET_KEY`: Django 시크릿 키
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`: 관리 DB 설정

선택적 환경 변수:
- `DJANGO_DEBUG`: 디버그 모드 (기본: False)
- `MAX_QUERY_RESULT_ROWS`: 결과 행 제한 (기본: 1000)
- `QUERY_TIMEOUT`: 쿼리 타임아웃 초 (기본: 300)
- `ENABLE_SCHEMA_DIFF`: 스키마 비교 활성화 (기본: True)

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
