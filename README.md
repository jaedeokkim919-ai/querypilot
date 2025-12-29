# QueryPilot

다중 데이터베이스 쿼리 관리 및 스키마 버전 관리를 위한 Django 기반 웹 애플리케이션입니다.

## 주요 기능

### 쿼리 에디터
- **CodeMirror 기반 SQL 에디터**: 문법 하이라이팅, 자동완성 지원
- **검수/실행 2단계 워크플로우**: 쿼리 검증 후 실행
- **다중 쿼리 배치 실행**: 세미콜론으로 구분된 여러 쿼리 한 번에 실행
- **트랜잭션 롤백**: 배치 실행 중 하나라도 실패 시 전체 롤백
- **작업자 추적**: 모든 쿼리 실행에 작업자 정보 기록

### 쿼리 검증
- **문법 검증**: EXPLAIN/PREPARE를 통한 SQL 문법 검사
- **Semantic 분석**:
  - INSERT: 컬럼 존재 여부, NOT NULL 제약조건 체크
  - UPDATE: SET/WHERE 절 컬럼 존재 여부 체크
  - DELETE: 외래키 참조 체크

### DDL 관리
- **스키마 버전 관리**: DDL 변경 시 자동 스키마 스냅샷 저장
- **전/후 비교**: 실행 이력에서 DDL 실행 전/후 스키마 비교 (Side-by-Side, DIFF)
- **온라인 DDL 분석**: ALTER 문에 대한 ALGORITHM, LOCK 옵션 제안

### 실행 이력
- **필터링**: 쿼리 유형(DDL/DML/DQL), 상태, 작업자별 검색
- **상세 조회**: 쿼리 텍스트, 실행 결과, 영향 행 수, 실행 시간
- **DDL 스키마 비교**: 전/후 스키마 차이 시각화

### 데이터베이스 연결
- **다중 연결 관리**: 여러 MySQL/MariaDB 데이터베이스 연결 관리
- **연결 테스트**: 실시간 연결 상태 확인
- **데이터베이스/테이블 탐색**: 연결된 DB의 구조 조회

### 대시보드
- **실시간 통계**: 총 연결 수, 실행 횟수, 성공률
- **최근 실행 이력**: 빠른 접근
- **쿼리 유형별 분석**

## 기술 스택

- **Backend**: Python 3.x, Django 3.2+
- **Database**: MySQL/MariaDB (PyMySQL)
- **Frontend**: Django Templates, Bootstrap 5.3, CodeMirror 5.x, Bootstrap Icons
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
├── CLAUDE.md                    # Claude Code 가이드
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
- `operator`, `executed_by`: 작업자/실행자 정보
- `execution_time`: 실행 시간
- `schema_before`, `schema_after`: DDL 변경 전후 스키마
- `batch_id`, `query_index`: 배치 실행 지원
- `validation_result`: 검증 결과

### SchemaVersion
스키마 버전 기록
- `connection`: 데이터베이스 연결
- `table_name`: 테이블 이름
- `version`: 버전 번호
- `schema_definition`: 스키마 정의
- `checksum`: 중복 방지용 체크섬
- `executed_by`: 실행자

### SchemaVersionTag
스키마 버전 태그
- `schema_version`: 스키마 버전
- `tag_name`: 태그 이름
- `memo`: 메모
- `created_by`: 생성자

## API 엔드포인트

### 쿼리 관련
| 엔드포인트 | 메소드 | 설명 |
|-----------|--------|------|
| `/query/execute/` | POST | 단일 쿼리 실행 |
| `/query/review/` | POST | 쿼리 검수 (검증만) |
| `/query/batch-execute/` | POST | 배치 쿼리 실행 |
| `/query/analyze-alter/` | POST | ALTER 문 분석 |

### 히스토리 관련
| 엔드포인트 | 메소드 | 설명 |
|-----------|--------|------|
| `/history/` | GET | 실행 이력 목록 |
| `/history/<pk>/` | GET | 실행 이력 상세 |
| `/history/<pk>/schema-compare/` | GET | DDL 스키마 비교 |

### 연결 관련
| 엔드포인트 | 메소드 | 설명 |
|-----------|--------|------|
| `/api/connections/<pk>/test/` | POST | 연결 테스트 |
| `/api/connections/<pk>/databases/` | GET | 데이터베이스 목록 |
| `/api/connections/<pk>/tables/` | GET | 테이블 목록 |
| `/api/connections/<pk>/tables/<table>/schema/` | GET | 테이블 스키마 |
| `/api/connections/<pk>/databases/<db>/tables/` | GET | 특정 DB 테이블 목록 |
| `/connections/<pk>/schema/diff/` | GET | 스키마 버전 비교 |

## 스크린샷

### 쿼리 에디터
- CodeMirror SQL 에디터
- 연결 선택 및 테스트
- 검수/실행 버튼
- 온라인 DDL 분석

### 실행 이력
- 필터링 (유형, 상태, 작업자)
- DDL 전/후 비교 버튼
- 상세 조회

### 대시보드
- 통계 카드
- 최근 실행 이력
- 연결 상태

## 라이선스

MIT License
