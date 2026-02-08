# 알라딘 API → 대시보드 파이프라인

#technical #pipeline #architecture

**상태:** ✅ 운영 중
**관련 파일:** `crawlers/aladin_api_crawler.py`, `scripts/franchise_sync.py`, `scripts/auto_crawl.py`, `dashboard.py`

---

## 개요

알라딘 API에서 도서 데이터를 크롤링하여 마진 분석 후 대시보드에 표시하고, 쿠팡 WING API로 상품을 등록하는 전체 파이프라인.

```
알라딘 API  →  Book(DB)  →  Product(DB)  →  대시보드 표시  →  WING API 등록  →  Listing(DB)
  크롤링        저장         마진계산        신규등록 페이지      쿠팡 등록          등록 기록
```

---

## 1단계: 알라딘 API 크롤링

**파일:** `crawlers/aladin_api_crawler.py`

### API 엔드포인트

| 메서드 | 엔드포인트 | 용도 |
|--------|-----------|------|
| `search_by_keyword()` | `ItemSearch.aspx` | 출판사명으로 키워드 검색 |
| `fetch_new_releases()` | `ItemList.aspx` | 신간 목록 조회 |
| `search_by_isbn()` | `ItemLookUp.aspx` | ISBN 단건 조회 |

### 인증 및 설정

- API 키: `.env`의 `ALADIN_TTB_KEY`
- 호출 간격: 0.5~1초 (`time.sleep`)
- 페이지당 최대 50건

### 데이터 파싱 (`_parse_item()`)

알라딘 API 응답에서 추출하는 필드:

```python
{
    "isbn": "9788901234567",        # 13자리 우선
    "title": "책 제목",
    "author": "저자명",
    "publisher": "출판사명",
    "original_price": 20000,         # 정가 (priceStandard, NOT 판매가)
    "publish_date": "2025-01-15",
    "page_count": 320,
    "sales_point": 1250,             # 알라딘 판매지수
    "image_url": "https://...",      # /coversum/ → /cover500/ 고화질 변환
    "year": 2025,                    # 제목에서 연도 추출
    "normalized_title": "...",       # 연도 제거한 정규화 제목
    "normalized_series": "..."       # 묶음 SKU용 시리즈명
}
```

### 연도 추출 로직 (`Book.extract_year()`)

- 4자리 패턴: `2020`~`2030` → 직접 매칭
- 2자리 패턴: `24년도`, `'24` 등 → 2000 + N
- 제외: `N학년` (학년 표기와 혼동 방지)

---

## 2단계: 자동 크롤링 데몬

**파일:** `scripts/auto_crawl.py` → `scripts/franchise_sync.py`

### 실행 방식

| 모드 | 설명 |
|------|------|
| 데몬 | 매일 새벽 3시 자동 실행 (기본) |
| `--now` | 즉시 1회 실행 |
| `--hour N` | 실행 시각 변경 |

### 크롤링 흐름 (`FranchiseSync.crawl_by_publisher()`)

```
24개 활성 출판사 순회:
│
├─ 1. 출판사명 + 별칭(aliases)으로 알라딘 검색
│     - PublishTime 정렬 (최신순)
│     - SalesPoint 정렬 (베스트셀러순)
│
├─ 2. 필터링
│     - 정가 ≥ 5,000원
│     - 제외 키워드: 사전, 잡지, 평가문제집
│     - 배치 내 ISBN 중복 제거
│
├─ 3. DB 중복 체크 (기존 ISBN dict로 O(1) 조회)
│     - 이미 존재 → sales_point만 배치 업데이트
│     - 신규 → Book 레코드 생성 (is_processed=False)
│
└─ 4. DB 커밋
```

### 반환값

```python
{
    "searched": 2831,      # 검색된 총 도서 수
    "new": 3,              # 신규 발견
    "skipped": 2828,       # 이미 DB에 있어 스킵
    "books": [Book, ...]   # 신규 Book 객체 목록
}
```

---

## 3단계: 마진 분석 → Product 생성

**파일:** `scripts/franchise_sync.py` (`analyze_products()`)
**핵심 계산:** `app/models/publisher.py` (`calculate_margin()`)

### 처리 흐름

```
is_processed=False인 Book 순회:
│
├─ 1. 해당 출판사(Publisher) 로드
├─ 2. 이미 Product 존재하는지 ISBN 체크
├─ 3. Product.create_from_book(book, publisher)
│     ├─ publisher.calculate_margin(list_price) → 마진 정보
│     ├─ publisher.determine_shipping_policy() → 배송 정책
│     └─ publisher.can_upload_single() → 등록 가능 여부
├─ 4. book.is_processed = True 마킹
└─ 5. Product DB 저장
```

### 마진 계산 공식

```python
sale_price    = list_price × 0.9          # 도서정가제 10% 할인
supply_cost   = list_price × supply_rate  # 출판사별 공급률 (40~73%)
coupang_fee   = sale_price × 0.11         # 쿠팡 수수료 11%
margin        = sale_price - supply_cost - coupang_fee
customer_fee  = determine_customer_shipping_fee(공급률, 정가)
seller_cost   = 2,300 - customer_fee      # 셀러 부담 배송비
net_margin    = margin - seller_cost      # 최종 순마진
can_upload    = net_margin >= 0           # 등록 가능 여부
```

### 계산 예시

**공급률 60%, 정가 20,000원:**

| 항목 | 금액 |
|------|------|
| 판매가 (정가×0.9) | 18,000원 |
| 공급가 (정가×0.6) | 12,000원 |
| 쿠팡 수수료 (판매가×0.11) | 1,980원 |
| 마진 | 4,020원 |
| 고객 배송비 (≥18,000 무료) | 0원 |
| 셀러 배송비 (2,300-0) | 2,300원 |
| **순마진** | **1,720원 ✓** |

→ `status='ready'`, `shipping_policy='free'`, `can_upload_single=True`

**공급률 73%, 정가 12,000원:**

| 항목 | 금액 |
|------|------|
| 판매가 | 10,800원 |
| 공급가 (정가×0.73) | 8,760원 |
| 쿠팡 수수료 | 1,188원 |
| 마진 | 852원 |
| 고객 배송비 (73%는 항상 유료) | 2,300원 |
| 셀러 배송비 (2,300-2,300) | 0원 |
| **순마진** | **852원 ✓** |

→ `status='ready'`, `shipping_policy='paid'`, `can_upload_single=True`

### 배송비 규칙 (`app/constants.py`)

`determine_customer_shipping_fee(margin_rate, list_price)` 함수 기준:

| 공급률 | 정가 조건 | 고객 배송비 | 배송 유형 |
|--------|----------|------------|----------|
| ≤55% | ≥15,000 | 0 (무료) | FREE |
| ≤55% | <15,000 | 2,300 | NOT_FREE |
| 56~60% | ≥18,000 | 0 (무료) | FREE |
| 56~60% | <18,000 | 2,300 | NOT_FREE |
| 61~62% | ≥18,000 | 0 (무료) | FREE |
| 61~62% | <18,000 | 2,000 | NOT_FREE |
| 63~65% | ≥20,500 | 0 (무료) | FREE |
| 63~65% | 18,000~20,000 | 1,000 | NOT_FREE |
| 63~65% | <18,000 | 2,300 | NOT_FREE |
| 66~70% | 18,500~29,000 | 1,000 | NOT_FREE |
| 66~70% | 15,000~18,000 | 2,000 | NOT_FREE |
| 66~70% | 그 외 | 2,300 | NOT_FREE |
| ≥71% | 항상 | 2,300 | CONDITIONAL_FREE (6만↑) |

> **seller_shipping_cost** = 2,300 - customer_fee (셀러가 실제 부담하는 배송비)

---

## 4단계: 대시보드 신규등록 페이지

**파일:** `dashboard.py` (line 1026~)

### 데이터 쿼리

```sql
SELECT p.id as product_id, b.title, b.author, b.publisher_name,
       b.isbn, b.image_url, b.list_price, p.sale_price, p.net_margin,
       p.shipping_policy, p.supply_rate, b.year, b.description,
       COALESCE(b.sales_point, 0) as sales_point,
       COALESCE(p.registration_status, 'approved') as registration_status,
       COALESCE(lc.listed_count, 0) as listed_count,
       COALESCE(lc.listed_accounts, '') as listed_accounts
FROM products p
JOIN books b ON p.book_id = b.id
LEFT JOIN (
    -- 계정별 등록 현황 서브쿼리
    SELECT match_key,
           COUNT(DISTINCT account_id) as listed_count,
           GROUP_CONCAT(DISTINCT account_name) as listed_accounts
    FROM listings l JOIN accounts a ON l.account_id = a.id
    GROUP BY match_key
) lc ON lc.match_key = COALESCE(b.isbn, b.title)
WHERE p.status = 'ready' AND p.can_upload_single = 1
ORDER BY sales_point DESC, net_margin DESC
```

### 화면 구성

```
┌─────────────────────────────────────────────────┐
│  KPI 카드                                        │
│  승인 N건 | 검토 대기 N건 | 거부 N건 | 전계정 완료 N건  │
├─────────────────────────────────────────────────┤
│  필터: 등록상태 / 출판사 / 최소마진 / 전계정 완료 숨김    │
├─────────────────────────────────────────────────┤
│  AgGrid 상품 테이블                                │
│  ☑ 제목 | 출판사 | 정가 | 판매가 | 순마진 | 판매지수   │
│    배송 | 등록상태 | 등록현황(2/5) | ISBN | 연도      │
│                                                  │
│  ☑ = 등록 선택 (일괄등록 매트릭스 연동)                │
│  행 클릭 = 상세보기 (수정/삭제/승인/거부)              │
├─────────────────────────────────────────────────┤
│  상세보기 (행 클릭 시)                              │
│  📖 이미지 | 제목, 저자, ISBN, 상태                  │
│  정가→판매가 | 순마진 | 등록 계정                     │
│  [승인] [거부]                                     │
│  ▶ 수정/삭제 (expander)                            │
├─────────────────────────────────────────────────┤
│  일괄등록 매트릭스 (체크된 상품)                      │
│           007-book  007-bm  007-ez  002-bm       │
│  상품 A    ✅       ☑       ☑      ✅             │
│  상품 B    ☑        ☑       ☑      ☑             │
│  ✅=이미 등록 | ☑=등록 예정 | 해제=제외               │
│                                                  │
│  등록 예정 6건 | □ Dry Run | [선택 항목 등록 (6건)]   │
└─────────────────────────────────────────────────┘
```

### 실시간 마진 재계산

대시보드에서는 DB 값을 그대로 쓰지 않고, 현재 공급률 기준으로 재계산하여 불일치 감지:

```python
def _recalc_margin(row):
    # 현재 supply_rate + list_price로 재계산
    # DB 값과 다르면 경고 표시
    return calc_sale, calc_supply, calc_fee, calc_margin, calc_net, calc_ship
```

### 상세보기 수정 폼

행 클릭 시 표시되는 편집 가능한 필드:

| 필드 | 대상 테이블 | 설명 |
|------|-----------|------|
| 제목 | books | 도서 제목 |
| 저자 | books | 저자명 |
| 출판사 | books | 출판사명 |
| 판매가 | products | 쿠팡 판매가 |
| 정가 | books | 도서 정가 |
| 배송 | products | free/paid |
| 이미지 URL | books | 표지 이미지 |
| 상품 설명 | books | 상세 설명 |

저장 시 products 테이블의 마진도 자동 재계산됨.

---

## 5단계: 쿠팡 WING API 등록

**파일:** `uploaders/coupang_api_uploader.py`

### 등록 요청 구조

```python
build_product_payload(product_data, outbound_code, return_code):
    {
        "displayCategoryCode": 도서 카테고리 코드 (int),
        "sellerProductName": 상품명,
        "vendorId": 벤더ID,
        "saleStartedAt": "YYYY-MM-DDTHH:MM:SS",
        "brand": 출판사명,
        "notices": [
            {"noticeCategoryName": "서적", ...ISBN/저자/출판사 고시}
        ],
        "attributes": [
            {"학습과목": "기타"}, {"사용학년/단계": "기타"}, {"ISBN": isbn}
        ],
        "items": [{
            "itemName": 상품명,
            "originalPrice": 정가,
            "salePrice": 판매가,
            "maximumBuyCount": 999,
            "outboundShippingTimeDay": 2,
            "images": [{"imageUrl": URL}],
            ...배송비 설정
        }],
        "outboundShippingPlaceCode": 출고지 코드 (int),
        "returnChargeName": 반품 정보,
        ...
    }
```

### 등록 결과 처리

```python
# 성공 시
res = {"success": True, "seller_product_id": "12345678"}

# listings 테이블에 INSERT
INSERT INTO listings (account_id, product_id, isbn, coupang_product_id,
                      coupang_status, sale_price, shipping_policy, uploaded_at)
VALUES (...)

# 전 계정(5개) 등록 완료 시
UPDATE products SET status = 'uploaded' WHERE id = :id
# → 신규등록 목록에서 자동 제거
```

---

## 6단계: 등록 후 관리

### Listing 테이블 (등록 기록)

| 필드 | 설명 |
|------|------|
| account_id | 등록된 쿠팡 계정 |
| coupang_product_id | 쿠팡 상품 ID |
| coupang_status | active / sold_out / pending |
| sale_price | 등록된 판매가 |
| stock_quantity | 재고 수량 |
| winner_status | 아이템 위너 여부 |
| vendor_item_id | 가격/재고 변경용 ID |

### 후속 동기화 스크립트

| 스크립트 | 기능 |
|---------|------|
| `sync_coupang_products.py` | 쿠팡 등록 상품 정보 DB 동기화 |
| `sync_item_winner.py` | 아이템 위너 상태 조회 |
| `sync_inventory.py` | 가격 변경 + 재고 리필 |
| `sync_orders.py` | 주문/발주서 동기화 |
| `sync_revenue.py` | 매출 데이터 동기화 |
| `sync_returns.py` | 반품/취소 동기화 |

---

## 데이터 모델 관계도

```
Publisher (24개, 공급률 40~73%)
    │ 1:N
    ▼
  Book (981+ 도서, 알라딘 크롤링)
    │ 1:1
    ▼
 Product (마진 계산 결과)
    │        status: ready → uploaded / excluded
    │        registration_status: pending_review → approved / rejected
    │ 1:N
    ▼
 Listing (계정별 등록 기록, 5계정 × N상품)
    │ 1:N
    ▼
 RevenueHistory (매출), Order (주문), ReturnRequest (반품)
```

### 상태 흐름도

```
[알라딘 크롤링]
      │
      ▼
Book (is_processed=False)
      │ analyze_products()
      ▼
Product (status=ready, registration_status=pending_review)
      │ 대시보드에서 승인
      ▼
Product (registration_status=approved)
      │ 일괄등록 버튼
      ▼
Listing (coupang_status=active)
      │ 전 계정 등록 완료?
      ▼
Product (status=uploaded) → 신규등록 목록에서 제거
```

---

## 핵심 파일 참조

| 컴포넌트 | 파일 | 주요 라인 |
|---------|------|----------|
| 알라딘 크롤러 | `crawlers/aladin_api_crawler.py` | 전체 |
| 자동 크롤링 | `scripts/auto_crawl.py` | 78~189 |
| 프랜차이즈 동기화 | `scripts/franchise_sync.py` | 201~504 |
| Book 모델 | `app/models/book.py` | 10~174 |
| Product 모델 | `app/models/product.py` | 9~153 |
| Publisher 모델 | `app/models/publisher.py` | 12~79 |
| Listing 모델 | `app/models/listing.py` | 9~153 |
| 배송비/마진 상수 | `app/constants.py` | 133~210 |
| 대시보드 신규등록 | `dashboard.py` | 1026~1455 |
| API 업로더 | `uploaders/coupang_api_uploader.py` | 전체 |

---

## 관련 문서

- [[배송비-수정-대상-쿠팡가격기준-2026-02-06]]
- [[아이템위너-모니터링]]
- [[Turso-libSQL-클라우드DB]]
