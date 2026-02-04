# 데이터베이스 스키마 V2

## 🎯 설계 목표

1. **계정별 ISBN 중복 방지** - (account_id, ISBN) 유니크 제약
2. **마진/배송 정책 저장** - 자동 판단 결과 기록
3. **연도 추출 및 시리즈 정규화** - 묶음 SKU 생성용
4. **묶음 SKU 관리** - 별도 테이블
5. **출판사별 공급률 관리** - 마진 계산용

---

## 📊 전체 테이블 구조 (8개)

```
1. accounts          - 계정 정보 (변경 없음)
2. publishers        - 출판사 정보 (신규, config/publishers.py → DB)
3. books             - 도서 원본 데이터 (kyobo_products → books 이름 변경)
4. products          - 단권 상품 (마진/배송 정보 추가)
5. bundle_skus       - 묶음 상품 (신규)
6. listings          - 계정별 업로드 현황 (중복 체크 강화)
7. sales             - 판매 데이터 (변경 없음)
8. analysis_results  - 분석 결과 (변경 없음)
```

---

## 1️⃣ accounts (계정 정보)

**변경 사항:** 없음

```sql
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name VARCHAR(100) UNIQUE NOT NULL,
    coupang_id VARCHAR(100) NOT NULL,
    encrypted_password TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    daily_upload_limit INTEGER DEFAULT 20,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 2️⃣ publishers (출판사 정보) ⭐ 신규

**목적:** config/publishers.py의 데이터를 DB로 이관

```sql
CREATE TABLE publishers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) UNIQUE NOT NULL,           -- 출판사명
    margin_rate INTEGER NOT NULL,                 -- 매입률(%) 40~73
    min_free_shipping INTEGER NOT NULL,           -- 무료배송 기준 (원)
    supply_rate REAL NOT NULL,                    -- 공급률 (0.40~0.73)
    is_active BOOLEAN DEFAULT 1,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE INDEX idx_publishers_name ON publishers(name);
CREATE INDEX idx_publishers_active ON publishers(is_active);
```

**초기 데이터:**
```python
# 40% (공급률 0.60)
("마린북스", 40, 9000, 0.60)
("아카데미소프트", 40, 9000, 0.60)
("렉스미디어", 40, 9000, 0.60)
("해람북스", 40, 9000, 0.60)

# 55% (공급률 0.45)
("크라운", 55, 14400, 0.45)
("영진", 55, 14400, 0.45)

# 60% (공급률 0.40)
("이퓨쳐", 60, 18000, 0.40)
("사회평론", 60, 18000, 0.40)
("길벗", 60, 18000, 0.40)
("아티오", 60, 18000, 0.40)
("이지스퍼블리싱", 60, 18000, 0.40)

# 65% (공급률 0.35)
("개념원리", 65, 23900, 0.35)
("이투스", 65, 23900, 0.35)
("비상교육", 65, 23900, 0.35)
("능률교육", 65, 23900, 0.35)
("씨톡", 65, 23900, 0.35)
("지학사", 65, 23900, 0.35)
("수경출판사", 65, 23900, 0.35)
("쏠티북스", 65, 23900, 0.35)
("마더텅", 65, 23900, 0.35)
("한빛미디어", 65, 23900, 0.35)

# 67% (공급률 0.33)
("동아", 67, 27600, 0.33)

# 70% (공급률 0.30)
("좋은책신사고", 70, 35800, 0.30)

# 73% (공급률 0.27)
("EBS", 73, 50800, 0.27)
("한국교육방송공사", 73, 50800, 0.27)
```

---

## 3️⃣ books (도서 원본 데이터) ⭐ 필드 추가

**변경 사항:**
- 테이블명: `kyobo_products` → `books`
- 추가 필드: `year`, `normalized_title`, `normalized_series`
- 출판사 외래키 추가

```sql
CREATE TABLE books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 기본 정보
    isbn VARCHAR(13) UNIQUE NOT NULL,
    title VARCHAR(500) NOT NULL,
    author VARCHAR(200),
    publisher_id INTEGER,                         -- ⭐ 외래키
    publisher_name VARCHAR(100),                  -- 검색 편의용 중복

    -- 가격
    list_price INTEGER NOT NULL,                  -- 정가

    -- 분류
    category VARCHAR(100),
    subcategory VARCHAR(100),

    -- 연도 및 정규화 ⭐ 신규
    year INTEGER,                                  -- 추출된 연도 (2024, 2025 등)
    normalized_title VARCHAR(500),                 -- 연도 제거된 제목
    normalized_series VARCHAR(200),                -- 시리즈명 (묶음용)

    -- 메타데이터
    image_url TEXT,
    description TEXT,
    source_url TEXT,                               -- 알라딘 URL
    publish_date DATE,
    page_count INTEGER,

    -- 상태
    is_processed BOOLEAN DEFAULT 0,
    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (publisher_id) REFERENCES publishers(id)
);

-- 인덱스
CREATE INDEX idx_books_isbn ON books(isbn);
CREATE INDEX idx_books_publisher ON books(publisher_id);
CREATE INDEX idx_books_year ON books(year);
CREATE INDEX idx_books_normalized_series ON books(normalized_series);
CREATE INDEX idx_books_processed ON books(is_processed);
```

**연도 추출 예시:**
```
"2025 수능완성 국어영역" → year=2025, normalized_title="수능완성 국어영역"
"개념원리 수학(상) 2024" → year=2024, normalized_series="개념원리 수학"
```

---

## 4️⃣ products (단권 상품) ⭐ 마진/배송 정보 추가

**변경 사항:**
- 마진 계산 결과 저장
- 배송 정책 저장
- 업로드 가능 여부 저장

```sql
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 도서 참조
    book_id INTEGER NOT NULL,
    isbn VARCHAR(13) NOT NULL,

    -- 가격 (도서정가제)
    list_price INTEGER NOT NULL,                  -- 정가
    sale_price INTEGER NOT NULL,                  -- 판매가 (정가 × 0.9)

    -- 마진 분석 ⭐ 신규
    supply_rate REAL NOT NULL,                    -- 공급률 (0.27~0.60)
    margin_per_unit INTEGER NOT NULL,             -- 권당 마진 (원)
    shipping_cost INTEGER DEFAULT 2000,           -- 배송비 (원)
    net_margin INTEGER NOT NULL,                  -- 순마진 (마진 - 배송비)

    -- 배송 정책 ⭐ 신규
    shipping_policy VARCHAR(20) NOT NULL,         -- 'free', 'paid', 'bundle_required'
    can_upload_single BOOLEAN DEFAULT 1,          -- 단권 업로드 가능 여부

    -- 상태
    status VARCHAR(20) DEFAULT 'ready',           -- ready, uploaded, excluded
    exclude_reason TEXT,                          -- 제외 사유

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (book_id) REFERENCES books(id)
);

-- 인덱스
CREATE INDEX idx_products_book ON products(book_id);
CREATE INDEX idx_products_isbn ON products(isbn);
CREATE INDEX idx_products_status ON products(status);
CREATE INDEX idx_products_shipping ON products(shipping_policy);
```

---

## 5️⃣ bundle_skus (묶음 상품) ⭐ 신규 테이블

**목적:** 저마진 도서를 묶어서 무료배송 가능하게 만듦

```sql
CREATE TABLE bundle_skus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 묶음 식별
    bundle_key VARCHAR(200) UNIQUE NOT NULL,      -- (publisher_id, normalized_series, year)
    bundle_name VARCHAR(300) NOT NULL,            -- "개념원리 수학 3종 세트 (2025)"

    -- 출판사/시리즈
    publisher_id INTEGER NOT NULL,
    normalized_series VARCHAR(200) NOT NULL,
    year INTEGER NOT NULL,

    -- 구성
    book_count INTEGER NOT NULL,                  -- 묶음 권수
    book_ids TEXT NOT NULL,                       -- JSON: [1, 2, 3]
    isbns TEXT NOT NULL,                          -- JSON: ["9781234", "9785678"]

    -- 가격 (도서정가제)
    total_list_price INTEGER NOT NULL,            -- 정가 합계
    total_sale_price INTEGER NOT NULL,            -- 판매가 합계 (정가 × 0.9)

    -- 마진 분석
    supply_rate REAL NOT NULL,
    total_margin INTEGER NOT NULL,                -- 총 마진
    shipping_cost INTEGER DEFAULT 2000,
    net_margin INTEGER NOT NULL,                  -- 순마진

    -- 배송 정책
    shipping_policy VARCHAR(20) DEFAULT 'free',   -- 묶음은 기본 무료배송

    -- 상태
    status VARCHAR(20) DEFAULT 'ready',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (publisher_id) REFERENCES publishers(id)
);

-- 인덱스
CREATE UNIQUE INDEX idx_bundle_key ON bundle_skus(bundle_key);
CREATE INDEX idx_bundle_publisher ON bundle_skus(publisher_id);
CREATE INDEX idx_bundle_series ON bundle_skus(normalized_series);
CREATE INDEX idx_bundle_year ON bundle_skus(year);
CREATE INDEX idx_bundle_status ON bundle_skus(status);
```

**묶음 키 생성 예시:**
```python
bundle_key = f"{publisher_id}_{normalized_series}_{year}"
# "12_개념원리수학_2025"
```

---

## 6️⃣ listings (계정별 업로드 현황) ⭐ 중복 체크 강화

**변경 사항:**
- `(account_id, isbn)` 유니크 제약 추가
- 묶음 SKU 지원

```sql
CREATE TABLE listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 계정
    account_id INTEGER NOT NULL,

    -- 상품 (단권 또는 묶음)
    product_type VARCHAR(20) NOT NULL,            -- 'single', 'bundle'
    product_id INTEGER,                           -- products.id (단권)
    bundle_id INTEGER,                            -- bundle_skus.id (묶음)
    isbn VARCHAR(13),                             -- 단권용
    bundle_key VARCHAR(200),                      -- 묶음용

    -- 쿠팡 정보
    coupang_product_id VARCHAR(50),               -- 쿠팡 상품 ID
    coupang_status VARCHAR(20),                   -- 'pending', 'active', 'sold_out'

    -- 판매 정보
    sale_price INTEGER NOT NULL,
    shipping_policy VARCHAR(20) NOT NULL,

    -- 타임스탬프
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_checked_at TIMESTAMP,

    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (product_id) REFERENCES products(id),
    FOREIGN KEY (bundle_id) REFERENCES bundle_skus(id),

    -- ⭐ 중복 방지: 동일 계정에서 동일 ISBN 재업로드 금지
    UNIQUE(account_id, isbn),
    UNIQUE(account_id, bundle_key)
);

-- 인덱스
CREATE INDEX idx_listings_account ON listings(account_id);
CREATE INDEX idx_listings_product_type ON listings(product_type);
CREATE INDEX idx_listings_isbn ON listings(isbn);
CREATE INDEX idx_listings_bundle ON listings(bundle_key);
CREATE INDEX idx_listings_status ON listings(coupang_status);
```

**중복 체크 로직:**
```python
# 업로드 전 체크
existing = db.query(Listing).filter(
    Listing.account_id == account_id,
    Listing.isbn == isbn
).first()

if existing:
    raise DuplicateError("이미 해당 계정에 업로드된 상품입니다")
```

---

## 7️⃣ sales (판매 데이터)

**변경 사항:** 없음 (나중에 분석용)

```sql
CREATE TABLE sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    sale_date DATE NOT NULL,
    quantity INTEGER DEFAULT 1,
    revenue INTEGER NOT NULL,
    cost INTEGER NOT NULL,
    profit INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (listing_id) REFERENCES listings(id),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE INDEX idx_sales_account ON sales(account_id);
CREATE INDEX idx_sales_date ON sales(sale_date);
CREATE INDEX idx_sales_listing ON sales(listing_id);
```

---

## 8️⃣ analysis_results (분석 결과)

**변경 사항:** 없음 (나중에 분석 엔진용)

```sql
CREATE TABLE analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    analysis_date DATE NOT NULL,
    problem_type VARCHAR(50),
    exposure_count INTEGER DEFAULT 0,
    click_count INTEGER DEFAULT 0,
    conversion_rate REAL DEFAULT 0.0,
    recommended_action TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (listing_id) REFERENCES listings(id)
);

CREATE INDEX idx_analysis_listing ON analysis_results(listing_id);
CREATE INDEX idx_analysis_date ON analysis_results(analysis_date);
CREATE INDEX idx_analysis_problem ON analysis_results(problem_type);
```

---

## 🔄 마이그레이션 전략

### 기존 데이터 이관

```python
# 1. publishers 테이블 생성 및 데이터 입력
# 2. kyobo_products → books 데이터 복사
# 3. publisher_name → publisher_id 매핑
# 4. 연도 추출 및 normalized_series 생성
# 5. 기존 테이블 삭제 또는 이름 변경
```

---

## 📊 ER 다이어그램

```
publishers (1) ──── (N) books
                         │
                         ├──── (1) products
                         │
                         └──── (N) bundle_skus

accounts (1) ──── (N) listings ───┬─── (1) products
                                   └─── (1) bundle_skus

listings (1) ──── (N) sales
listings (1) ──── (N) analysis_results
```

---

## 🎯 핵심 쿼리 예시

### 1. 중복 체크 (계정별 ISBN)
```sql
SELECT * FROM listings
WHERE account_id = ? AND isbn = ?;
```

### 2. 무료배송 가능한 단권 찾기
```sql
SELECT * FROM products
WHERE net_margin >= 0
AND shipping_policy = 'free'
AND can_upload_single = 1
AND status = 'ready';
```

### 3. 묶음 생성 대상 찾기
```sql
SELECT
    publisher_id,
    normalized_series,
    year,
    COUNT(*) as book_count,
    SUM(list_price) as total_price
FROM books
WHERE year IS NOT NULL
AND publisher_id IN (SELECT id FROM publishers WHERE supply_rate >= 0.30)
GROUP BY publisher_id, normalized_series, year
HAVING book_count >= 2;
```

### 4. 계정별 업로드 가능 상품 (중복 제외)
```sql
SELECT p.* FROM products p
WHERE p.status = 'ready'
AND p.can_upload_single = 1
AND p.isbn NOT IN (
    SELECT isbn FROM listings WHERE account_id = ?
);
```

---

## 🚀 다음 단계

1. ✅ 스키마 확정
2. ⏭️ SQLAlchemy 모델 업데이트
3. ⏭️ 마이그레이션 스크립트 작성
4. ⏭️ 출판사 데이터 초기화
5. ⏭️ 연도 추출 로직 구현
6. ⏭️ 마진 계산 모듈 구현
7. ⏭️ 묶음 SKU 생성기 구현

---

**이 스키마로 확정할까?**
