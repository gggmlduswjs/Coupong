# 쿠팡 WING API 연동

#feature #api #wing #phase2

**상태:** ✅ Step 1 완료 (클라이언트 + 동기화), Step 2 완료 (API 업로더)
**구현 파일:**
- `app/api/coupang_wing_client.py` - WING API 클라이언트
- `scripts/sync_coupang_products.py` - 상품 동기화 스크립트
- `uploaders/coupang_api_uploader.py` - API 기반 상품 등록

---

## 개요

쿠팡 WING Open API를 통해 5개 계정의 상품을 직접 관리한다. 기존 엑셀 다운로드/수동 CSV 업로드 방식 대신 **API 직접 연동**으로 전환.

## 5개 계정 정보

| 계정 | vendor_id | 용도 |
|------|-----------|------|
| 007-book | A01105984 | 메인 |
| 007-bm | A00317195 | 서브 |
| 007-ez | A01234216 | 서브 |
| 002-bm | A01163064 | 서브 |
| big6ceo | A01258837 | 서브 |

**API 키 만료:** 2026.08.04 (180일)

## 핵심 구현

### 1. HMAC-SHA256 인증 (`coupang_wing_client.py`)

```python
class CoupangWingClient:
    BASE_URL = "https://api-gateway.coupang.com"
    RATE_LIMIT_INTERVAL = 0.1  # 10 calls/sec

    def _generate_hmac(self, method, path, query=""):
        # {datetime}{method}{path}{query} → HMAC-SHA256 서명
        ...

    def _request(self, method, path, params=None, data=None):
        # Rate limit 준수 + HMAC 인증 + 공통 에러 처리
        ...
```

### 2. 주요 엔드포인트

| 기능 | 메서드 | 구현 |
|------|--------|------|
| 상품 목록 | `list_products()` | nextToken 자동 페이징 |
| 상품 조회 | `get_product(id)` | 단건 상세 |
| 상품 등록 | `create_product(data)` | JSON 페이로드 |
| 상품 수정 | `update_product(id, data)` | 부분 업데이트 |
| 재고/가격 | `update_inventory(id, qty, price)` | 실시간 변경 |
| 카테고리 추천 | `recommend_category(name)` | 상품명 기반 |
| 출고지 조회 | `get_outbound_shipping_places()` | 물류 코드 |
| 반품지 조회 | `get_return_shipping_centers()` | 반품 코드 |
| 발주서 조회 | `get_ordersheets(from, to)` | 주문 관리 |

### 3. 상품 동기화 (`sync_coupang_products.py`)

```
흐름:
1. DB에서 WING API 활성 계정 로드
2. 각 계정별 CoupangWingClient 생성
3. list_products()로 전체 상품 목록 가져오기
4. 각 상품에서 ISBN 추출 (barcode → searchTags → productName)
5. listings 테이블에 upsert
6. 결과 리포트 출력
```

### 4. 출고지/반품지 코드 조회 (`setup_shipping_places.py`)

```bash
python scripts/setup_shipping_places.py              # 전체 5계정
python scripts/setup_shipping_places.py --check-category  # 카테고리도 확인
```

| 계정 | 출고지코드 | 반품지코드 |
|------|-----------|-----------|
| 007-book | 24105055 | 1002509459 |
| 007-bm | 3818765 | 1002504253 |
| 007-ez | 21009623 | 1002504172 |
| 002-bm | 20884668 | 1002504202 |
| big6ceo | 21307952 | 1002514534 |

### 5. API 상품 등록 (`coupang_api_uploader.py`) - 테스트 완료

CSV 생성 로직을 API JSON 포맷으로 변환:
- `recommend_category()` → 카테고리 추천 API (캐시 포함)
- `build_product_payload()` → WING API 등록용 JSON
- `upload_product()` → 단건 등록 (응답 code 검증 포함)
- `upload_batch()` → 일괄 등록
- 도서 고시정보(서적), 필수 속성(학습과목/학년/ISBN), 검색 태그, 상세 HTML 자동 생성

**API 등록 시 핵심 필드:**
- `notices`: `noticeCategoryName = "서적"` (NOT "도서"), 7개 항목 각각 개별 객체
- `attributes`: 학습과목, 사용학년/단계, ISBN (필수), 저자, 출판사
- `outboundShippingTimeDay`: item 레벨에 위치 (product 레벨 아님)
- `vendorUserId`, `saleStartedAt`, 반품 주소 정보 필수
- `certifications: [{"certificationType": "NOT_REQUIRED"}]`

## 도서 상품 기본값

```python
BOOK_PRODUCT_DEFAULTS = {
    "deliveryMethod": "SEQUENCIAL",       # 일반배송
    "deliveryChargeType": "FREE",         # 무료배송
    "taxType": "FREE",                    # 도서 비과세
    "offerCondition": "NEW",
    "outboundShippingTimeDay": 1,         # D+1 출고
    "returnCharge": 2500,
    "pccNeeded": False,                   # 불리언 (문자열 아님)
    ...
}
```

## Account 모델 확장

```python
# 추가된 필드
vendor_id = Column(String(20))           # WING vendor ID
wing_access_key = Column(String(100))    # API access key
wing_secret_key = Column(String(100))    # API secret key
wing_api_enabled = Column(Boolean)       # API 활성 여부
outbound_shipping_code = Column(String(50))  # 출고지 코드
return_center_code = Column(String(50))      # 반품지 코드
```

## 사용법

```bash
# 전체 5계정 동기화
python scripts/sync_coupang_products.py

# 특정 계정만
python scripts/sync_coupang_products.py --account 007-bm

# 출고지/반품지 코드 조회 + 카테고리 확인
python scripts/setup_shipping_places.py --check-category

# API 상품 등록 테스트
python scripts/test_api_upload.py --account 007-book --isbn 9788961334839

# dry-run (등록 안 함, 페이로드만 확인)
python scripts/test_api_upload.py --dry-run

# 파이프라인에 통합됨 (6단계 중 5번째)
python scripts/run_pipeline.py
```

## 파이프라인 변경

기존 5단계 → **6단계**로 확장:
1. DB 초기화
2. 출판사/계정 시딩 + **WING API 연결**
3. 알라딘 API 검색
4. 마진 분석
5. **WING API 상품 동기화** (신규)
6. CSV 생성

## 관련 문서

- [[Dashboard]] - 전체 진행률
- [[쿠팡-엑셀-동기화]] - 이전 엑셀 기반 동기화 설계 (API로 대체)
- [[Database-Schema-V2]] - listings 테이블 구조
