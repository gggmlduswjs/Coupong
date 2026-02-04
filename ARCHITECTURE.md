# 쿠팡 도서 판매 자동화 시스템 아키텍처

## 📋 목차
1. [시스템 개요](#시스템-개요)
2. [기술 스택](#기술-스택)
3. [디렉토리 구조](#디렉토리-구조)
4. [데이터베이스 스키마](#데이터베이스-스키마)
5. [모듈 설계](#모듈-설계)
6. [데이터 플로우](#데이터-플로우)
7. [API 설계](#api-설계)
8. [배포 전략](#배포-전략)

---

## 시스템 개요

### 핵심 기능
1. **크롤링 엔진**: 교보문고 신간 교재 자동 수집
2. **상품 프로세서**: 쿠팡 업로드용 데이터 자동 생성
3. **업로드 엔진**: 5개 계정 자동 업로드 (CSV/Playwright)
4. **분석 엔진**: 판매 부진 원인 분석 (노출 vs 전환)
5. **대시보드**: 엄마용 간단 UI (Streamlit)

### 핵심 제약
- 도서 가격 고정: 정가 × 0.9
- 계정 5개 동시 운영
- 약관 위반 최소화
- 실제 작동 필수

---

## 기술 스택

### Backend
```
- Python 3.11+
- FastAPI (REST API)
- SQLite → PostgreSQL (나중에 마이그레이션)
- SQLAlchemy (ORM)
- Celery + Redis (비동기 작업)
```

### 크롤링/자동화
```
- Playwright (교보문고 크롤링, 쿠팡 업로드)
- BeautifulSoup4 (HTML 파싱)
- Pandas (데이터 처리)
```

### 대시보드
```
- Streamlit (엄마용 UI)
- Plotly (차트)
```

### 인프라
```
- Docker + Docker Compose
- Nginx (리버스 프록시)
- GitHub Actions (CI/CD)
```

### 보안
```
- python-dotenv (환경변수)
- cryptography (계정 정보 암호화)
```

---

## 디렉토리 구조

```
coupang-auto/
│
├── README.md
├── ARCHITECTURE.md (이 파일)
├── requirements.txt
├── .env.example
├── .gitignore
├── docker-compose.yml
│
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 엔트리포인트
│   ├── config.py                  # 설정 관리
│   ├── database.py                # DB 연결
│   │
│   ├── models/                    # SQLAlchemy 모델
│   │   ├── __init__.py
│   │   ├── account.py             # 계정 정보
│   │   ├── product.py             # 상품 마스터
│   │   ├── listing.py             # 계정별 상품 등록 현황
│   │   ├── sales.py               # 판매 데이터
│   │   └── task.py                # 작업 로그
│   │
│   ├── schemas/                   # Pydantic 스키마
│   │   ├── __init__.py
│   │   ├── product.py
│   │   ├── listing.py
│   │   └── sales.py
│   │
│   ├── services/                  # 비즈니스 로직
│   │   ├── __init__.py
│   │   ├── crawler_service.py     # 크롤링 로직
│   │   ├── product_service.py     # 상품 생성 로직
│   │   ├── uploader_service.py    # 업로드 로직
│   │   └── analyzer_service.py    # 분석 로직
│   │
│   ├── tasks/                     # Celery 비동기 작업
│   │   ├── __init__.py
│   │   ├── crawl_tasks.py
│   │   ├── upload_tasks.py
│   │   └── analyze_tasks.py
│   │
│   ├── api/                       # API 엔드포인트
│   │   ├── __init__.py
│   │   ├── products.py
│   │   ├── listings.py
│   │   ├── sales.py
│   │   └── tasks.py
│   │
│   └── utils/                     # 유틸리티
│       ├── __init__.py
│       ├── encryption.py          # 암호화
│       ├── rate_limiter.py        # 속도 제한
│       └── logger.py              # 로깅
│
├── crawlers/                      # 크롤러 모듈
│   ├── __init__.py
│   ├── base_crawler.py            # 베이스 클래스
│   ├── kyobo_crawler.py           # 교보문고
│   ├── yes24_crawler.py           # YES24 (확장용)
│   └── aladin_crawler.py          # 알라딘 (확장용)
│
├── uploaders/                     # 업로더 모듈
│   ├── __init__.py
│   ├── base_uploader.py           # 베이스 클래스
│   ├── csv_uploader.py            # CSV 생성
│   └── playwright_uploader.py     # 브라우저 자동화
│
├── analyzers/                     # 분석 모듈
│   ├── __init__.py
│   ├── exposure_analyzer.py       # 노출 분석
│   ├── conversion_analyzer.py     # 전환 분석
│   └── recommendation_engine.py   # 액션 추천
│
├── dashboard/                     # Streamlit 대시보드
│   ├── Home.py                    # 메인 페이지
│   ├── pages/
│   │   ├── 1_📊_오늘_할_일.py
│   │   ├── 2_📈_판매_분석.py
│   │   ├── 3_⬆️_업로드_관리.py
│   │   └── 4_⚙️_설정.py
│   └── components/
│       ├── __init__.py
│       └── charts.py
│
├── data/                          # 데이터 저장소
│   ├── raw/                       # 크롤링 원본
│   ├── processed/                 # 가공된 데이터
│   ├── uploads/                   # 업로드용 CSV
│   └── reports/                   # 분석 리포트
│
├── sessions/                      # 계정 세션 (Git 제외)
│   └── .gitkeep
│
├── logs/                          # 로그 파일
│   └── .gitkeep
│
├── tests/                         # 테스트
│   ├── __init__.py
│   ├── test_crawlers.py
│   ├── test_uploaders.py
│   └── test_analyzers.py
│
└── scripts/                       # 실행 스크립트
    ├── init_db.py                 # DB 초기화
    ├── crawl_kyobo.py             # 수동 크롤링
    ├── generate_csv.py            # CSV 생성
    └── scheduler.py               # 스케줄러
```

---

## 데이터베이스 스키마

### ERD 개념도
```
accounts (계정 정보)
    ↓
listings (계정별 상품 등록)
    ↓
products (상품 마스터) ← kyobo_products (크롤링 원본)
    ↓
sales (판매 데이터)
    ↓
analysis_results (분석 결과)
```

### 테이블 정의

#### 1. accounts (계정 정보)
```sql
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name VARCHAR(50) NOT NULL UNIQUE,  -- 'account_1', 'account_2', ...
    email VARCHAR(100) NOT NULL,
    password_encrypted TEXT NOT NULL,          -- 암호화된 비밀번호
    session_file VARCHAR(255),                 -- Playwright 세션 파일 경로
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 2. kyobo_products (교보문고 크롤링 원본)
```sql
CREATE TABLE kyobo_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isbn VARCHAR(13) UNIQUE NOT NULL,
    title VARCHAR(500) NOT NULL,
    author VARCHAR(200),
    publisher VARCHAR(100),
    publish_date DATE,
    original_price INTEGER NOT NULL,           -- 정가
    category VARCHAR(100),
    subcategory VARCHAR(100),
    image_url TEXT,
    description TEXT,
    kyobo_url TEXT,
    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_processed BOOLEAN DEFAULT FALSE         -- products 테이블로 변환 여부
);
```

#### 3. products (상품 마스터)
```sql
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isbn VARCHAR(13) UNIQUE NOT NULL,
    product_name VARCHAR(500) NOT NULL,        -- 최적화된 상품명
    original_price INTEGER NOT NULL,           -- 정가
    sale_price INTEGER NOT NULL,               -- 판매가 (정가 × 0.9)
    publisher VARCHAR(100),
    category VARCHAR(100),
    description TEXT,                          -- 자동 생성된 상세 설명
    main_image_url TEXT,
    detail_images JSON,                        -- ["url1", "url2", ...]
    keywords JSON,                             -- ["키워드1", "키워드2", ...]
    status VARCHAR(20) DEFAULT 'ready',        -- ready, uploaded, selling, stopped
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (isbn) REFERENCES kyobo_products(isbn)
);
```

#### 4. listings (계정별 상품 등록 현황)
```sql
CREATE TABLE listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    coupang_product_id VARCHAR(50),            -- 쿠팡 상품 ID
    seller_sku VARCHAR(100),                   -- 판매자 SKU
    listing_status VARCHAR(20) DEFAULT 'pending', -- pending, uploaded, active, stopped
    upload_method VARCHAR(20),                 -- csv, playwright
    uploaded_at TIMESTAMP,
    last_synced_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, product_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);
```

#### 5. sales (판매 데이터)
```sql
CREATE TABLE sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    date DATE NOT NULL,
    views INTEGER DEFAULT 0,                   -- 조회수
    clicks INTEGER DEFAULT 0,                  -- 클릭수
    orders INTEGER DEFAULT 0,                  -- 주문수
    revenue INTEGER DEFAULT 0,                 -- 매출
    refunds INTEGER DEFAULT 0,                 -- 환불
    stock INTEGER DEFAULT 0,                   -- 재고
    ranking INTEGER,                           -- 카테고리 순위
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(listing_id, date),
    FOREIGN KEY (listing_id) REFERENCES listings(id)
);
```

#### 6. analysis_results (분석 결과)
```sql
CREATE TABLE analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    analysis_date DATE NOT NULL,
    period_days INTEGER DEFAULT 7,             -- 분석 기간 (7일/30일)
    total_views INTEGER,
    total_orders INTEGER,
    conversion_rate REAL,                      -- 전환율 (%)
    problem_type VARCHAR(50),                  -- exposure_low, conversion_low, normal
    priority_score REAL,                       -- 우선순위 점수 (0-100)
    recommended_actions JSON,                  -- [{"action": "...", "reason": "..."}]
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (listing_id) REFERENCES listings(id)
);
```

#### 7. tasks (작업 로그)
```sql
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type VARCHAR(50) NOT NULL,            -- crawl, upload, analyze
    status VARCHAR(20) DEFAULT 'pending',      -- pending, running, success, failed
    params JSON,                               -- 작업 파라미터
    result JSON,                               -- 작업 결과
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 모듈 설계

### 1. Crawler Service

```python
# app/services/crawler_service.py

from typing import List, Dict
from crawlers.kyobo_crawler import KyoboCrawler
from app.models.kyobo_product import KyoboProduct

class CrawlerService:
    """크롤링 서비스"""

    async def crawl_new_books(
        self,
        category: str = "초등교재",
        limit: int = 50
    ) -> List[Dict]:
        """신간 크롤링"""
        crawler = KyoboCrawler()
        raw_data = await crawler.crawl(category, limit)

        # DB 저장
        saved_products = []
        for item in raw_data:
            product = await self._save_kyobo_product(item)
            saved_products.append(product)

        return saved_products

    async def _save_kyobo_product(self, data: Dict) -> KyoboProduct:
        """크롤링 데이터 DB 저장"""
        # 중복 체크 (ISBN)
        # 저장 로직
        pass
```

### 2. Product Service

```python
# app/services/product_service.py

class ProductService:
    """상품 생성/관리 서비스"""

    async def create_product_from_kyobo(
        self,
        kyobo_product_id: int
    ) -> Product:
        """교보문고 데이터 → 쿠팡 상품 생성"""
        kyobo = await self._get_kyobo_product(kyobo_product_id)

        product_data = {
            "isbn": kyobo.isbn,
            "product_name": self._optimize_title(kyobo.title),
            "original_price": kyobo.original_price,
            "sale_price": int(kyobo.original_price * 0.9),
            "publisher": kyobo.publisher,
            "category": kyobo.category,
            "description": self._generate_description(kyobo),
            "keywords": self._extract_keywords(kyobo),
            "main_image_url": kyobo.image_url
        }

        return await Product.create(**product_data)

    def _optimize_title(self, original_title: str) -> str:
        """상품명 최적화 (SEO 키워드 추가)"""
        # "초등 수학 문제집 3학년"
        # → "초등 수학 문제집 3학년 [2025 최신판] 10% 할인"
        pass

    def _generate_description(self, kyobo) -> str:
        """상세 설명 자동 생성"""
        template = f"""
        📚 {kyobo.title}

        ✅ 출판사: {kyobo.publisher}
        ✅ 정가: {kyobo.original_price:,}원
        ✅ 할인가: {int(kyobo.original_price * 0.9):,}원 (10% 할인)

        {kyobo.description}
        """
        return template.strip()
```

### 3. Uploader Service

```python
# app/services/uploader_service.py

class UploaderService:
    """업로드 서비스"""

    async def upload_to_accounts(
        self,
        product_id: int,
        account_ids: List[int],
        method: str = "csv"  # csv or playwright
    ):
        """여러 계정에 상품 업로드"""
        product = await Product.get(product_id)

        for account_id in account_ids:
            if method == "csv":
                await self._upload_via_csv(product, account_id)
            else:
                await self._upload_via_playwright(product, account_id)

    async def _upload_via_csv(self, product, account_id):
        """CSV 대량등록"""
        csv_data = self._generate_csv_row(product)
        # CSV 파일에 추가
        # listings 테이블 업데이트
        pass

    async def _upload_via_playwright(self, product, account_id):
        """브라우저 자동화 업로드"""
        from uploaders.playwright_uploader import PlaywrightUploader

        uploader = PlaywrightUploader(account_id)
        result = await uploader.upload(product)

        # listings 테이블 업데이트
        await Listing.create(
            account_id=account_id,
            product_id=product.id,
            listing_status='uploaded',
            upload_method='playwright',
            uploaded_at=datetime.now()
        )
```

### 4. Analyzer Service

```python
# app/services/analyzer_service.py

class AnalyzerService:
    """판매 분석 서비스"""

    async def analyze_listing(
        self,
        listing_id: int,
        period_days: int = 7
    ) -> Dict:
        """개별 상품 분석"""
        sales_data = await self._get_sales_data(listing_id, period_days)

        total_views = sum(s.views for s in sales_data)
        total_orders = sum(s.orders for s in sales_data)

        # 분류
        if total_views < 10:
            problem_type = "exposure_low"
            actions = [
                {"action": "상품명 키워드 최적화", "reason": "검색 노출 부족"},
                {"action": "카테고리 재설정", "reason": "잘못된 카테고리 가능성"},
                {"action": "대표 이미지 교체", "reason": "클릭 유도 부족"}
            ]
        elif total_views > 50 and total_orders == 0:
            problem_type = "conversion_low"
            actions = [
                {"action": "가격 검토", "reason": "경쟁사 대비 높을 가능성"},
                {"action": "상세 페이지 보강", "reason": "구매 설득력 부족"},
                {"action": "리뷰 확보", "reason": "신뢰도 부족"}
            ]
        else:
            problem_type = "normal"
            actions = [{"action": "현재 유지", "reason": "정상 판매 중"}]

        # 우선순위 점수 계산
        priority_score = self._calculate_priority(
            total_views,
            total_orders,
            problem_type
        )

        # 저장
        result = await AnalysisResult.create(
            listing_id=listing_id,
            analysis_date=date.today(),
            period_days=period_days,
            total_views=total_views,
            total_orders=total_orders,
            conversion_rate=(total_orders / total_views * 100) if total_views > 0 else 0,
            problem_type=problem_type,
            priority_score=priority_score,
            recommended_actions=actions
        )

        return result

    def _calculate_priority(self, views, orders, problem_type) -> float:
        """우선순위 점수 (0-100)"""
        # 조회는 많은데 구매 없으면 높은 점수 (개선 가능성 높음)
        if problem_type == "conversion_low":
            return min(100, views * 2)

        # 노출 부족이면 중간 점수
        elif problem_type == "exposure_low":
            return 50

        # 정상이면 낮은 점수
        else:
            return 10
```

---

## 데이터 플로우

### 전체 흐름도

```
[1. 크롤링 단계]
교보문고 → KyoboCrawler → kyobo_products 테이블
         (매일 자동)

[2. 상품 생성 단계]
kyobo_products → ProductService → products 테이블
              (수동 승인 or 자동)

[3. 업로드 단계]
products → UploaderService → CSV 생성 or Playwright
        → listings 테이블 (계정별 5개 레코드)

[4. 판매 데이터 수집]
쿠팡 판매자센터 리포트 → 파일 업로드 → sales 테이블

[5. 분석 단계]
sales → AnalyzerService → analysis_results 테이블

[6. 액션 추천]
analysis_results → 대시보드 → 엄마가 승인 → 자동 실행
```

### 상세 시퀀스 (하루 일과)

```
08:00 - [Celery Scheduler] 크롤링 작업 시작
  ├─ KyoboCrawler.crawl("초등교재", limit=50)
  ├─ 신간 30권 발견
  └─ kyobo_products 테이블 저장

09:00 - [Celery] 상품 생성 작업
  ├─ 미처리 kyobo_products 조회
  ├─ ProductService.create_product_from_kyobo()
  │   ├─ 상품명 최적화
  │   ├─ 가격 계산 (정가 × 0.9)
  │   └─ 키워드 추출
  └─ products 테이블 저장 (30개)

10:00 - [알림] 엄마에게 카톡/이메일
  "신규 상품 30개 준비됨. 승인 대기 중입니다."

11:00 - [엄마 작업] 대시보드 접속
  ├─ 상품 리스트 확인
  ├─ [일괄 승인] 버튼 클릭
  └─ upload_task 큐에 추가

11:05 - [Celery] 업로드 작업 시작
  ├─ 계정 1: 30개 상품 업로드 (CSV 생성)
  ├─ 30분 대기
  ├─ 계정 2: 30개 상품 업로드
  ├─ ...
  └─ 계정 5 완료 (총 2.5시간)

14:00 - [완료 알림]
  "150개 상품 업로드 완료 (30개 × 5계정)"

18:00 - [Celery] 판매 데이터 수집
  ├─ 판매자센터 로그인 (5개 계정)
  ├─ 리포트 다운로드
  └─ sales 테이블 업데이트

19:00 - [Celery] 판매 분석
  ├─ 7일간 판매 0건 상품 추출 (50개)
  ├─ AnalyzerService.analyze_listing()
  └─ 우선순위 TOP 10 선정

20:00 - [알림] 주간 리포트
  "이번 주 개선 필요 상품 10개"
  + 대시보드 링크
```

---

## API 설계

### REST API 엔드포인트

```python
# app/api/products.py

from fastapi import APIRouter, Depends
from typing import List
from app.schemas.product import ProductResponse, ProductCreate

router = APIRouter(prefix="/api/products", tags=["products"])

@router.get("/", response_model=List[ProductResponse])
async def get_products(
    skip: int = 0,
    limit: int = 100,
    status: str = None
):
    """상품 목록 조회"""
    pass

@router.post("/", response_model=ProductResponse)
async def create_product(product: ProductCreate):
    """상품 생성"""
    pass

@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: int):
    """상품 상세 조회"""
    pass

@router.post("/{product_id}/upload")
async def upload_product(
    product_id: int,
    account_ids: List[int],
    method: str = "csv"
):
    """상품 업로드"""
    # Celery 작업 큐에 추가
    from app.tasks.upload_tasks import upload_to_accounts
    task = upload_to_accounts.delay(product_id, account_ids, method)
    return {"task_id": task.id}
```

```python
# app/api/sales.py

router = APIRouter(prefix="/api/sales", tags=["sales"])

@router.get("/listings/{listing_id}")
async def get_listing_sales(
    listing_id: int,
    days: int = 7
):
    """특정 상품의 판매 데이터"""
    pass

@router.get("/analysis/{listing_id}")
async def get_listing_analysis(listing_id: int):
    """특정 상품의 분석 결과"""
    pass

@router.get("/recommendations")
async def get_recommendations(limit: int = 10):
    """우선순위 액션 추천 TOP N"""
    pass
```

```python
# app/api/tasks.py

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

@router.post("/crawl")
async def start_crawl_task(
    category: str = "초등교재",
    limit: int = 50
):
    """크롤링 작업 시작"""
    from app.tasks.crawl_tasks import crawl_kyobo
    task = crawl_kyobo.delay(category, limit)
    return {"task_id": task.id}

@router.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """작업 상태 조회"""
    from celery.result import AsyncResult
    result = AsyncResult(task_id)
    return {
        "status": result.status,
        "result": result.result if result.ready() else None
    }
```

---

## 배포 전략

### Docker Compose 구성

```yaml
# docker-compose.yml

version: '3.8'

services:
  # FastAPI 백엔드
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/coupang_auto
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - ./app:/app
      - ./data:/data
      - ./sessions:/sessions
    depends_on:
      - db
      - redis
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  # Celery Worker
  celery_worker:
    build: .
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/coupang_auto
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - ./app:/app
      - ./data:/data
      - ./sessions:/sessions
    depends_on:
      - db
      - redis
    command: celery -A app.tasks worker --loglevel=info

  # Celery Beat (스케줄러)
  celery_beat:
    build: .
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/coupang_auto
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    command: celery -A app.tasks beat --loglevel=info

  # Streamlit 대시보드
  dashboard:
    build:
      context: .
      dockerfile: Dockerfile.dashboard
    ports:
      - "8501:8501"
    environment:
      - API_URL=http://api:8000
    volumes:
      - ./dashboard:/dashboard
    command: streamlit run dashboard/Home.py

  # PostgreSQL
  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=coupang_auto
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  # Redis
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

### 환경변수 (.env)

```env
# .env.example

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/coupang_auto

# Redis
REDIS_URL=redis://localhost:6379/0

# Encryption
ENCRYPTION_KEY=your-32-byte-key-here

# Coupang Accounts (암호화된 값)
ACCOUNT_1_EMAIL=encrypted_email_1
ACCOUNT_1_PASSWORD=encrypted_password_1
# ... 5개 계정

# Crawler Settings
CRAWL_DELAY_MIN=1
CRAWL_DELAY_MAX=3
CRAWL_MAX_ITEMS=100

# Upload Settings
UPLOAD_DELAY_MIN=5
UPLOAD_DELAY_MAX=10
UPLOAD_MAX_DAILY=20

# Notification
KAKAO_API_KEY=your_kakao_key
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_FROM=your@email.com
EMAIL_TO=mom@email.com
```

### 실행 방법

```bash
# 1. 환경 설정
cp .env.example .env
# .env 파일 수정

# 2. Docker 컨테이너 시작
docker-compose up -d

# 3. DB 초기화
docker-compose exec api python scripts/init_db.py

# 4. 계정 정보 등록 (암호화)
docker-compose exec api python scripts/register_accounts.py

# 5. 대시보드 접속
# http://localhost:8501

# 6. API 문서
# http://localhost:8000/docs
```

---

## 보안 설계

### 계정 정보 암호화

```python
# app/utils/encryption.py

from cryptography.fernet import Fernet
import os

class EncryptionManager:
    def __init__(self):
        key = os.getenv("ENCRYPTION_KEY").encode()
        self.cipher = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """암호화"""
        return self.cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """복호화"""
        return self.cipher.decrypt(ciphertext.encode()).decode()

# 사용 예시
encryptor = EncryptionManager()

# 계정 정보 저장 시
email_encrypted = encryptor.encrypt("seller1@example.com")
password_encrypted = encryptor.encrypt("password123")

# 사용 시
email = encryptor.decrypt(email_encrypted)
password = encryptor.decrypt(password_encrypted)
```

### Rate Limiting

```python
# app/utils/rate_limiter.py

import time
import random
from functools import wraps

class RateLimiter:
    """속도 제한"""

    def __init__(self, min_delay: float = 1.0, max_delay: float = 3.0):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.last_request_time = {}

    def wait(self, key: str = "default"):
        """요청 전 대기"""
        now = time.time()

        if key in self.last_request_time:
            elapsed = now - self.last_request_time[key]
            required_delay = random.uniform(self.min_delay, self.max_delay)

            if elapsed < required_delay:
                sleep_time = required_delay - elapsed
                time.sleep(sleep_time)

        self.last_request_time[key] = time.time()

# 사용 예시
limiter = RateLimiter(min_delay=1.0, max_delay=3.0)

for product in products:
    limiter.wait("kyobo_crawler")
    crawl(product)
```

---

## 모니터링/로깅

```python
# app/utils/logger.py

import logging
from logging.handlers import RotatingFileHandler
import os

def setup_logger(name: str, log_file: str = None):
    """로거 설정"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # 포맷
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 파일 핸들러
    if log_file:
        os.makedirs("logs", exist_ok=True)
        file_handler = RotatingFileHandler(
            f"logs/{log_file}",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

# 사용 예시
logger = setup_logger("crawler", "crawler.log")
logger.info("크롤링 시작")
logger.error("크롤링 실패", exc_info=True)
```

---

## 확장 가능성

### Phase 1 (MVP - 1~2주)
- 교보문고 크롤링
- CSV 대량등록
- 간단한 판매 분석
- Streamlit 대시보드

### Phase 2 (V1 - 3~4주)
- Playwright 자동 업로드
- 5개 계정 동시 운영
- 노출/전환 분석
- 우선순위 추천

### Phase 3 (V2 - 이후)
- YES24, 알라딘 크롤링 추가
- 가격 모니터링 (경쟁사)
- A/B 테스트 (계정별 전략 비교)
- LLM 기반 상품명/설명 자동 생성
- 자동 리뷰 응답

---

## 다음 단계

1. **지금 바로**: 폴더 구조 생성 + requirements.txt 작성
2. **내일**: DB 스키마 구현 + 첫 크롤러 작성
3. **모레**: CSV 생성 로직 + 대시보드 프로토타입

어떤 부분부터 시작할까요?
