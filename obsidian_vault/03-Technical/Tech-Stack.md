# Tech Stack

#technical #stack #technology

**작성일:** 2026-02-05
**업데이트:** 2026-02-05

---

## 📊 기술 스택 개요

```
┌─────────────────────────────────────────┐
│           APPLICATION LAYER              │
│  Python 3.11+ (Core Language)           │
└─────────────────┬───────────────────────┘
                  │
        ┌─────────┴─────────┐
        │                   │
┌───────▼────────┐  ┌──────▼──────────┐
│   DATA LAYER   │  │  EXTERNAL APIs  │
│  SQLAlchemy    │  │  Aladin API     │
│  SQLite        │  │                 │
└───────┬────────┘  └─────────────────┘
        │
┌───────▼────────────────────────────────┐
│         DOCUMENTATION LAYER            │
│  Obsidian + Markdown                   │
└────────────────────────────────────────┘
```

---

## 🐍 Core: Python 3.11+

### 선택 이유
- **타입 힌트:** 코드 안정성 및 IDE 지원
- **성능:** 3.11부터 대폭 향상 (10-60% 빠름)
- **생태계:** 풍부한 라이브러리
- **ORM 지원:** SQLAlchemy와 완벽한 호환

### 주요 기능 활용
```python
# Type Hints
def calculate_margin(price: int, rate: float) -> dict[str, int]:
    ...

# Dataclasses
from dataclasses import dataclass

@dataclass
class MarginResult:
    net_margin: int
    shipping_policy: str

# Pattern Matching (3.10+)
match shipping_policy:
    case 'free':
        return 0
    case 'paid':
        return 2000
```

---

## 🗄️ Database: SQLite

### 선택 이유
- **파일 기반:** 설치 불필요, 이식성 높음
- **간단함:** 설정 없이 바로 사용
- **성능:** 작은~중간 규모에 충분
- **안정성:** ACID 트랜잭션 지원

### 사용 현황
```
파일: coupang.db
크기: ~10MB (초기)
테이블: 8개
인덱스: 15개
제약조건: UNIQUE, FOREIGN KEY
```

### 주요 설정
```python
# database.py
engine = create_engine(
    "sqlite:///coupang.db",
    echo=False,  # SQL 로그 출력
    pool_pre_ping=True,  # 연결 체크
    connect_args={"check_same_thread": False}
)
```

### 한계 및 대안
```
현재: SQLite (개발/소규모)
대안: PostgreSQL (확장 시)

마이그레이션:
- SQLAlchemy로 추상화되어 있어 쉽게 전환 가능
- DATABASE_URL만 변경하면 됨
```

---

## 🔗 ORM: SQLAlchemy 2.0

### 선택 이유
- **표준:** Python ORM 사실상 표준
- **타입 안전:** 2.0에서 타입 힌트 대폭 개선
- **관계 매핑:** ForeignKey, relationship 완벽 지원
- **쿼리 빌더:** Pythonic한 쿼리 작성

### 버전
```
SQLAlchemy 2.0.23
- 새로운 선언형 스타일
- 타입 힌트 개선
- 성능 향상
```

### 주요 기능 활용

#### 1. 모델 정의
```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Publisher(Base):
    __tablename__ = "publishers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    margin_rate: Mapped[int]
```

#### 2. 관계 정의
```python
class Book(Base):
    __tablename__ = "books"

    publisher_id: Mapped[int] = mapped_column(ForeignKey("publishers.id"))
    publisher: Mapped["Publisher"] = relationship(back_populates="books")

class Publisher(Base):
    books: Mapped[list["Book"]] = relationship(back_populates="publisher")
```

#### 3. 제약조건
```python
from sqlalchemy import UniqueConstraint

class Listing(Base):
    __table_args__ = (
        UniqueConstraint("account_id", "isbn", name="uix_account_isbn"),
    )
```

#### 4. 쿼리
```python
# 단순 조회
books = db.query(Book).filter(Book.year == 2025).all()

# JOIN
books_with_publisher = db.query(Book).join(Publisher).all()

# 집계
from sqlalchemy import func
stats = db.query(
    func.count(Book.id),
    func.avg(Book.list_price)
).first()
```

---

## ⚙️ Configuration: Pydantic

### 선택 이유
- **타입 검증:** 자동 타입 체크 및 변환
- **환경 변수:** .env 파일 자동 로드
- **문서화:** 자동 스키마 생성
- **성능:** Rust 기반 빠른 검증

### 버전
```
pydantic 2.5.0
pydantic-settings 2.1.0
```

### 사용 예시
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 알라딘 API
    aladin_ttb_key: str | None = None

    # DB
    database_url: str = "sqlite:///coupang.db"

    # Obsidian
    obsidian_vault_path: str = "obsidian_vault"

    # 계정
    default_daily_upload_limit: int = 20
    num_accounts: int = 5

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# 사용
settings = Settings()
print(settings.aladin_ttb_key)
```

---

## 🌐 HTTP Client: Requests

### 선택 이유
- **간단함:** 사용하기 쉬운 API
- **신뢰성:** 검증된 라이브러리
- **기능:** 타임아웃, 재시도, 세션 관리

### 버전
```
requests 2.31.0
```

### 사용 예시
```python
import requests

response = requests.get(
    url="https://www.aladin.co.kr/ttb/api/ItemSearch.aspx",
    params={
        "TTBKey": ttb_key,
        "Query": "수능완성",
        "MaxResults": 50,
        "Output": "JS"
    },
    timeout=10
)

if response.status_code == 200:
    data = response.json()
```

---

## 🔌 External API: 알라딘 Open API

### API 정보
- **제공자:** 알라딘
- **인증:** TTBKey
- **포맷:** JSON/XML
- **제한:** 일일 5000건 (무료)

### 주요 엔드포인트

#### 1. ItemSearch (도서 검색)
```
GET https://www.aladin.co.kr/ttb/api/ItemSearch.aspx

Parameters:
- TTBKey: 인증 키
- Query: 검색어
- QueryType: Keyword, Title, Author, Publisher
- MaxResults: 최대 결과 수 (1-50)
- Start: 시작 위치 (페이징)
- Output: JS (JSON), XML
- Version: 20131101
```

#### 2. ItemLookUp (상세 조회)
```
GET https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx

Parameters:
- TTBKey: 인증 키
- ItemId: 상품 ID
- ItemIdType: ISBN, ItemId
- Output: JS, XML
```

### 응답 예시
```json
{
  "item": [
    {
      "isbn": "9788954429871",
      "title": "2025 수능완성 국어영역",
      "author": "EBS",
      "pubDate": "2024-03-05",
      "priceStandard": 8000,
      "priceSales": 7200,
      "publisher": "한국교육방송공사",
      "categoryName": "국내도서>초등학교참고서",
      "cover": "https://..."
    }
  ]
}
```

### 사용 현황
```python
from crawlers.aladin_api_crawler import AladinAPICrawler

crawler = AladinAPICrawler()
books = crawler.search_books(
    query="수능완성",
    max_results=100
)
# 연도 자동 추출 포함
```

---

## 📝 Documentation: Obsidian

### 선택 이유
- **Markdown:** 표준 포맷
- **백링크:** 문서 간 연결
- **로컬 파일:** Git으로 버전 관리
- **플러그인:** 확장 가능

### 구조
```
obsidian_vault/
├── 00-Index/        메인 대시보드
├── 01-Daily/        일일 개발 로그
├── 02-Features/     기능 문서
├── 03-Technical/    기술 문서
└── 04-Decisions/    의사결정 기록
```

### 자동 로깅
```python
from obsidian_logger import ObsidianLogger

logger = ObsidianLogger()
logger.log_feature("마진 계산", "출판사별 마진 자동 계산")
logger.log_to_daily("작업 완료", "✅")
```

### 플러그인 (선택사항)
- **Text Generator:** Claude API 통합
- **Dataview:** 동적 쿼리
- **Templater:** 템플릿 자동화

---

## 🛠️ Development Tools

### Version Control
```
Git
- 브랜치 전략: main (프로덕션)
- .gitignore: .env, *.db, output/
```

### IDE
```
VS Code (추천)
- 확장: Python, SQLite Viewer
- 설정: .vscode/settings.json

PyCharm (대안)
- Professional: SQLAlchemy 지원
```

### Testing (선택사항)
```
pytest
- 단위 테스트
- 통합 테스트
- 픽스처
```

### Linting (선택사항)
```
ruff (추천)
- 빠른 린터
- 자동 포맷팅

mypy
- 정적 타입 체크
```

---

## 📦 Dependencies

### requirements.txt
```
# Core
SQLAlchemy==2.0.23
pydantic==2.5.0
pydantic-settings==2.1.0

# HTTP
requests==2.31.0

# Environment
python-dotenv==1.0.0

# Testing (선택)
pytest==7.4.3
pytest-cov==4.1.0

# Linting (선택)
ruff==0.1.6
mypy==1.7.1
```

### 설치
```bash
pip install -r requirements.txt
```

---

## 🔮 향후 확장 계획

### Phase 2: 분석 대시보드
```
Streamlit
- 인터랙티브 대시보드
- 실시간 차트
- 계정별 성과 분석
```

### Phase 3: 자동화
```
Selenium
- 쿠팡 자동 로그인
- 자동 상품 업로드
- 스크린샷 저장

APScheduler
- 일일 자동 크롤링
- 판매 데이터 수집
```

### Phase 4: 확장
```
PostgreSQL
- 대용량 데이터 처리
- 동시 접속 지원

Redis
- 캐싱
- 세션 관리

FastAPI
- REST API 제공
- 웹 인터페이스
```

---

## 📊 성능 고려사항

### 현재 성능
```
- 크롤링: ~100건/분
- DB 쿼리: <10ms (인덱스 활용)
- CSV 생성: <1초
- 전체 워크플로우: ~5분 (100권 기준)
```

### 최적화 포인트
```
1. 배치 처리
   - 건별 커밋 → 배치 커밋
   - 100건: 10초 → 1초

2. 인덱스 활용
   - isbn, year, normalized_series

3. 캐싱
   - 출판사 정보 (거의 변경 없음)

4. 비동기 처리 (향후)
   - httpx (async requests)
   - asyncio
```

---

## 🔗 관련 문서

- [[프로젝트-개요]] - 프로젝트 전체 개요
- [[시스템-아키텍처]] - 시스템 구조
- [[파일-구조]] - 파일 구조
- [[설정-가이드]] - 설정 방법

---

## 📚 참고 자료

### 공식 문서
- [Python](https://docs.python.org/3/)
- [SQLAlchemy](https://docs.sqlalchemy.org/)
- [Pydantic](https://docs.pydantic.dev/)
- [Requests](https://requests.readthedocs.io/)
- [알라딘 API](https://blog.aladin.co.kr/openapi)

### 튜토리얼
- [SQLAlchemy 2.0 Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/)
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

---

**작성:** 2026-02-05
**상태:** 문서화 완료
