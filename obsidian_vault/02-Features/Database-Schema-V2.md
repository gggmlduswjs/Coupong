# Database Schema V2

#feature #database #schema

**상태:** ✅ 완료
**구현 파일:** `app/models/` 디렉토리

---

## 개요

SQLAlchemy ORM 기반 8개 테이블. 도서 수집 → 마진 분석 → 묶음 생성 → 계정별 업로드까지 전체 파이프라인 데이터를 관리한다.

## 테이블 구조

### 1. publishers (출판사)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | |
| name | String UNIQUE | 출판사명 |
| margin_rate | Integer | 매입율 (40~73%) |
| supply_rate | Float | 공급률 (= 1 - margin_rate/100) |
| min_free_shipping | Integer | 무료배송 최소 정가 |

- 24개 출판사 사전 등록 (`config/publishers.py`)
- 마진율 범위: 마린북스 40% ~ EBS 73%

### 2. books (도서)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | |
| isbn | String UNIQUE | ISBN |
| title | String | 원본 제목 |
| author | String | 저자 |
| publisher_id | Integer FK | publishers.id |
| list_price | Integer | 정가 |
| year | Integer | 추출된 연도 |
| normalized_title | String | 연도 제거된 제목 |
| normalized_series | String | 시리즈명 |

- `extract_year()`: 제목에서 연도 자동 추출
- `normalize_title()`: 연도 제거
- `extract_series()`: 시리즈명 추출 (묶음용)

### 3. products (단권 상품)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | |
| isbn | String UNIQUE | books.isbn |
| list_price | Integer | 정가 |
| sale_price | Integer | 판매가 (정가 × 0.9) |
| supply_rate | Float | 공급률 |
| margin_per_unit | Integer | 권당 마진 |
| net_margin | Integer | 순마진 (배송비 차감) |
| shipping_policy | String | free / paid / bundle_required |
| status | String | ready / uploaded / excluded |

### 4. bundle_skus (묶음 상품)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | |
| bundle_key | String UNIQUE | `{publisher_id}_{series}_{year}` |
| bundle_name | String | 묶음 상품명 |
| book_ids | Text (JSON) | 구성 도서 ID 목록 |
| isbns | Text (JSON) | 구성 ISBN 목록 |
| book_count | Integer | 구성 권수 (2~5) |
| net_margin | Integer | 묶음 순마진 |
| shipping_policy | String | free / paid / unprofitable |

### 5. listings (등록 현황)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | |
| account_id | Integer FK | accounts.id |
| product_type | String | single / bundle |
| isbn | String | 단권 ISBN |
| bundle_key | String | 묶음 키 |
| coupang_product_id | String | 쿠팡 상품 ID |
| coupang_status | String | pending / active / sold_out |

**중복 방지 제약조건:**
```sql
UNIQUE(account_id, isbn)       -- 같은 계정에 같은 단권 중복 등록 방지
UNIQUE(account_id, bundle_key) -- 같은 계정에 같은 묶음 중복 등록 방지
```

### 6. accounts (쿠팡 계정)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | |
| account_name | String UNIQUE | 계정명 |
| email | String | 이메일 |
| password_encrypted | String | 암호화된 비밀번호 |

- 5개 계정: 007-book, 007-ez, 007-bm, 002-bm, big6ceo

### 7. sales (판매 데이터)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | |
| listing_id | Integer FK | listings.id |
| date | Date | 판매일 |
| views / clicks / orders | Integer | 조회/클릭/주문 |
| revenue | Integer | 매출 |
| refunds | Integer | 환불 |

### 8. analysis_results (분석 결과)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | |
| listing_id | Integer FK | listings.id |
| problem_type | String | 문제 유형 |
| priority_score | Float | 우선순위 점수 |
| recommended_actions | Text | 권장 조치 |

## 테이블 관계도

```
publishers ─1:N─> books ─1:1─> products
                    │
                    └─N:M─> bundle_skus

accounts ─1:N─> listings ─1:N─> sales
                    │
                    └─1:N─> analysis_results
```

## 관련 문서

- [[마진-계산기]] - products 테이블 마진 계산 로직
- [[묶음-SKU-생성기]] - bundle_skus 생성 로직
- [[알라딘-API-크롤러]] - books 데이터 수집
