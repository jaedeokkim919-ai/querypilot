# QueryPilot

다중 데이터베이스 쿼리 관리 및 스키마 버전 관리를 위한 Django 기반 웹 애플리케이션입니다.

## 주요 기능

- **데이터베이스 연결 관리**: 여러 MySQL/MariaDB 데이터베이스 연결을 중앙에서 관리
- **쿼리 실행**: 웹 인터페이스를 통한 SQL 쿼리 실행 (SELECT, INSERT, UPDATE, DELETE, DDL)
- **쿼리 히스토리**: 모든 쿼리 실행 기록 추적 및 감사
- **스키마 버전 관리**: DDL 변경 시 자동 스키마 스냅샷 저장
- **ALTER 문 분석**: ALTER 문에 대한 최적화 제안 제공
- **대시보드**: 실시간 통계 및 분석

## 기술 스택

- **Backend**: Python 3.x, Django 3.2+
- **Database**: MySQL/MariaDB (PyMySQL)
- **Frontend**: Django Templates, Bootstrap, CodeMirror
- **Production**: Gunicorn, WhiteNoise

## 설치 방법

### 1. 저장소 클론

```bash
git clone <repository-url>
cd querypilot
```

### 2. 가상환경 생성 및 활성화

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python -m venv venv
source venv/bin/activate
```

### 3. 의존성 설치

```bash
pip install -r requirements.txt
```

### 4. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 실제 설정값으로 수정:

```env
# Django 설정
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# 관리 데이터베이스 설정
DB_NAME=querypilot
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=localhost
DB_PORT=3306

# QueryPilot 기능 설정
MAX_QUERY_RESULT_ROWS=1000
QUERY_TIMEOUT=300
ENABLE_SCHEMA_DIFF=True
```

### 5. 데이터베이스 마이그레이션

```bash
python manage.py migrate
```

### 6. 관리자 계정 생성

```bash
python manage.py createsuperuser
```

## 실행 방법

### 개발 환경

```bash
python manage.py runserver
```

- 애플리케이션: http://localhost:8000
- 관리자 페이지: http://localhost:8000/admin

### 프로덕션 환경

```bash
gunicorn -c gunicorn_config.py querypilot.wsgi
```

또는 환경 변수로 설정:

```bash
GUNICORN_BIND=0.0.0.0:8000 GUNICORN_WORKERS=4 gunicorn querypilot.wsgi
```

## 프로젝트 구조

```
querypilot/
├── manage.py                    # Django 관리 스크립트
├── gunicorn_config.py           # Gunicorn 프로덕션 서버 설정
├── requirements.txt             # Python 의존성
├── .env.example                 # 환경 변수 템플릿
│
├── querypilot/                  # Django 프로젝트 설정
│   ├── settings.py              # Django 설정
│   ├── urls.py                  # 루트 URL 라우팅
│   └── wsgi.py                  # WSGI 진입점
│
├── query_manager/               # 메인 애플리케이션
│   ├── models.py                # 데이터 모델
│   ├── views.py                 # 뷰 로직 및 API
│   ├── services.py              # 비즈니스 로직 (QueryService)
│   ├── forms.py                 # Django 폼
│   ├── urls.py                  # URL 라우팅
│   ├── templates/               # HTML 템플릿
│   └── migrations/              # 데이터베이스 마이그레이션
│
├── static/                      # 정적 파일
└── logs/                        # 애플리케이션 로그
```

## 주요 모델

### DatabaseConnection
데이터베이스 연결 정보 저장
- `name`: 연결 이름
- `host`, `port`: 서버 주소
- `database`, `schema`: 데이터베이스/스키마 이름
- `username`, `password`: 인증 정보
- `is_active`: 활성화 상태

### QueryExecution
쿼리 실행 기록
- `connection`: 데이터베이스 연결
- `query_text`: 실행된 쿼리
- `query_type`: 쿼리 유형 (SELECT, INSERT, UPDATE, DELETE, DDL)
- `status`: 실행 결과 (SUCCESS, FAILED)
- `execution_time`: 실행 시간
- `schema_before`, `schema_after`: DDL 변경 전후 스키마

### SchemaVersion
스키마 버전 기록
- `connection`: 데이터베이스 연결
- `table_name`: 테이블 이름
- `version`: 버전 번호
- `schema_definition`: 스키마 정의
- `checksum`: 중복 방지용 체크섬

## API 엔드포인트

| 엔드포인트 | 메소드 | 설명 |
|-----------|--------|------|
| `/api/connections/<pk>/test/` | POST | 연결 테스트 |
| `/api/connections/<pk>/databases/` | GET | 데이터베이스 목록 |
| `/api/connections/<pk>/tables/` | GET | 테이블 목록 |
| `/api/connections/<pk>/tables/<table>/schema/` | GET | 테이블 스키마 |
| `/query/execute/` | POST | 쿼리 실행 |
| `/query/analyze-alter/` | POST | ALTER 문 분석 |
| `/connections/<pk>/schema/diff/` | GET | 스키마 버전 비교 |

## 라이선스

MIT License
