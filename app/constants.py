"""비즈니스 상수 - 매직넘버 중앙 관리"""

# 도서정가제 (한국 법률)
BOOK_DISCOUNT_RATE = 0.9  # 정가 × 0.9 = 판매가

# 쿠팡 수수료
COUPANG_FEE_RATE = 0.11  # 판매가의 11%

# 배송비
DEFAULT_SHIPPING_COST = 2300  # 실제 택배비 (원)
FREE_SHIPPING_THRESHOLD = 2000  # (레거시) 무료배송 순마진 기준 — 신규: determine_customer_shipping_fee() 사용
TARGET_MARGIN_MIN = 1300  # 목표 최소 마진 (원)
TARGET_MARGIN_MAX = 2000  # 목표 최대 마진 (원)
CONDITIONAL_FREE_THRESHOLD = 20000     # 기본 조건부 무료배송 기준 (원)
CONDITIONAL_FREE_THRESHOLD_67 = 25000  # 공급률 67% 조건부 무료배송 기준 (원)
CONDITIONAL_FREE_THRESHOLD_70 = 30000  # 공급률 70% 조건부 무료배송 기준 (원)
CONDITIONAL_FREE_THRESHOLD_73 = 60000  # 공급률 73% 조건부 무료배송 기준 (원)

# 재고
DEFAULT_STOCK = 10  # 기본 재고 수량
DEFAULT_LEAD_TIME = 2  # 출고 소요일
LOW_STOCK_THRESHOLD = 3  # 재고 부족 기준 (이하면 리필)

# ──── 안전장치 (스크립트 일괄 실행 차단) ────
# 각 Lock이 True인 한 스크립트에서 해당 API 호출 차단
# 대시보드 개별 조작만 허용 (dashboard_override=True 파라미터 필요)
PRICE_LOCK = True       # 가격 변경 차단 (update_price, update_original_price, update_inventory)
DELETE_LOCK = True      # 상품 삭제 차단 (delete_product)
SALE_STOP_LOCK = True   # 판매 중지 차단 (stop_item_sale)
REGISTER_LOCK = True    # 상품 등록 차단 (create_product)

# API
API_THROTTLE_SECONDS = 1.0  # 알라딘 API 호출 간격 (초)
COUPANG_WING_RATE_LIMIT = 0.1  # WING API 호출 간격 (초, 10 calls/sec)

# 쿠팡 WING API - 도서 상품 등록 기본값 (PDF 가이드 기반)
# 마진 계산: 순마진 = 판매가 - 공급가 - 수수료 - 배송비(무료배송 시)
# CONDITIONAL_FREE: 20,000원 미만 → 고객 부담, 이상 → 무료(셀러 부담)
BOOK_PRODUCT_DEFAULTS = {
    "deliveryMethod": "SEQUENCIAL",              # 일반배송
    "deliveryChargeType": "CONDITIONAL_FREE",     # 조건부 무료배송 (20,000원 이상 무료)
    "deliveryCharge": DEFAULT_SHIPPING_COST,        # 미달 시 고객 부담 배송비 (= 실제 택배비)
    "freeShipOverAmount": CONDITIONAL_FREE_THRESHOLD,  # 조건부 무료배송 기준 금액 (20,000원)
    "deliveryChargeOnReturn": DEFAULT_SHIPPING_COST,
    "unionDeliveryType": "UNION_DELIVERY",
    "remoteAreaDeliverable": "N",
    "returnCharge": DEFAULT_SHIPPING_COST,
    "requested": True,                           # 자동 판매승인 요청
    "adultOnly": "EVERYONE",
    "taxType": "FREE",                           # 도서 비과세
    "parallelImported": "NOT_PARALLEL_IMPORTED",
    "overseasPurchased": "NOT_OVERSEAS_PURCHASED",
    "pccNeeded": False,                          # 불리언 (문자열 아님)
    "offerCondition": "NEW",
    "outboundShippingTimeDay": 1,                # 정수 (D+1 출고)
    "maximumBuyForPerson": 0,                    # 정수 (무제한)
}

# 쿠팡 도서 카테고리 코드
# 카테고리 추천 API 결과: 교재류는 76236(고등교재), 76239(기타교재), 76243(수험서) 등
# 추천 API 실패 시 기본값으로 사용
BOOK_CATEGORY_CODE = "76236"  # 기본 도서 카테고리 (고등교재)

# 도서 카테고리 코드 매핑 (참고용)
BOOK_CATEGORY_MAP = {
    "76236": "고등교재",
    "76239": "기타교재",
    "76243": "수험서",
    "35171": "고등교재",
    "76001": "국내도서",
}

# WING API 계정별 환경변수 매핑 (account_name → env_prefix)
WING_ACCOUNT_ENV_MAP = {
    "007-book": "COUPANG_007BOOK",
    "007-bm":   "COUPANG_007BM",
    "007-ez":   "COUPANG_007EZ",
    "002-bm":   "COUPANG_002BM",
    "big6ceo":  "COUPANG_BIG6CEO",
}

# ─────────────────────────────────────────────
# 동기화 설정 (sync 스크립트 공통)
# ─────────────────────────────────────────────
SYNC_CONFIG = {
    "batch_size": 50,           # 배치 커밋 단위
    "retry_max_attempts": 3,    # API 재시도 횟수
    "retry_base_delay": 1.0,    # 재시도 기본 대기 (초)
    "stale_hours": 24,          # 상세 재조회 기준 시간
}

# ─────────────────────────────────────────────
# 타임아웃 설정
# ─────────────────────────────────────────────
TIMEOUT_CONFIG = {
    "api_request": 30,          # API 요청 타임아웃 (초)
    "db_busy": 30000,           # SQLite busy 타임아웃 (ms)
    "db_connect": 30,           # DB 연결 타임아웃 (초)
}

# ─────────────────────────────────────────────
# 자동 크롤링 설정
# ─────────────────────────────────────────────
AUTO_CRAWL_CONFIG = {
    "crawl_hour": 3,            # 실행 시각 (새벽 3시)
    "max_per_publisher": 50,    # 출판사당 최대 검색 수
    "year_filter": 2025,        # 검색 연도 필터
    "check_interval": 30,       # 스케줄 체크 간격 (초)
    "max_items_safety": 200,    # 1회 최대 처리 아이템
}

# ─────────────────────────────────────────────
# 크롤링 제외 필터
# ─────────────────────────────────────────────
CRAWL_MIN_PRICE = 5000          # 정가 최소 기준 (미만 제외)
CRAWL_EXCLUDE_KEYWORDS = [      # 제목/카테고리에 포함 시 제외
    "사전", "잡지", "월간지", "자습서", "평가문제집",
]

# ─────────────────────────────────────────────
# 가격/마진 설정
# ─────────────────────────────────────────────
PRICE_CONFIG = {
    "min_margin": 1300,         # 최소 마진 (원) - 이 이하면 판매 비권장
    "target_margin": 2000,      # 목표 마진 (원)
    "min_margin_rate": 0.05,    # 최소 마진율 (5%)
    "bundle_threshold": 2000,   # 묶음 판매 기준 마진 (원)
}

# ─────────────────────────────────────────────
# 배송비 결정 함수 (공급률 + 정가 기준)
# ─────────────────────────────────────────────
def determine_customer_shipping_fee(margin_rate: int, list_price: int) -> int:
    """
    공급률(매입률)과 정가 기준으로 고객 부담 배송비 결정

    규칙:
      공급률 ~55%: 정가 ≥ 15,000 → 무료 / 미만 → 2,300
      공급률 ~60%: 정가 ≥ 18,000 → 무료 / 미만 → 2,300
      공급률 ~62%: 정가 ≥ 18,000 → 무료 / 미만 → 2,000
      공급률 ~65%: 정가 ≥ 20,500 → 무료 / 18,000~20,000 → 1,000 / 미만 → 2,300
      공급률 ~70%: 18,500~29,000 → 1,000 / 15,000~18,000 → 2,000 / 그 외 → 2,300
      공급률 73%+: 항상 2,300 (조건부 60,000원 무료)

    Args:
        margin_rate: 매입률/공급률 (정수 40~73)
        list_price: 정가 (원)

    Returns:
        고객 부담 배송비 (0=무료, 1000, 2000, 2300)
    """
    if margin_rate <= 55:
        # 공급률 ~55%: 15,000원 이상 무료배송
        return 0 if list_price >= 15000 else DEFAULT_SHIPPING_COST

    if margin_rate <= 60:
        # 공급률 56~60%: 18,000원 이상 무료배송
        return 0 if list_price >= 18000 else DEFAULT_SHIPPING_COST

    if margin_rate <= 62:
        # 공급률 61~62%: 18,000원 이상 무료 / 미만 → 2,000
        return 0 if list_price >= 18000 else 2000

    if margin_rate <= 65:
        # 공급률 63~65%: 20,500 이상 무료 / 18,000~20,000 → 1,000
        if list_price >= 20500:
            return 0
        if 18000 <= list_price <= 20000:
            return 1000
        return DEFAULT_SHIPPING_COST

    if margin_rate <= 70:
        # 공급률 66~70%: 18,500~29,000 → 1,000 / 15,000~18,000 → 2,000
        if 18500 <= list_price <= 29000:
            return 1000
        if 15000 <= list_price <= 18000:
            return 2000
        return DEFAULT_SHIPPING_COST

    # 공급률 73%+: 항상 2,300원 (조건부 60,000원 무료배송)
    return DEFAULT_SHIPPING_COST


def determine_delivery_charge_type(margin_rate: int, list_price: int) -> tuple:
    """
    배송비 유형 + 금액 + 무료배송 기준 결정 (WING API용)

    Returns:
        (deliveryChargeType, deliveryCharge, freeShipOverAmount)
    """
    customer_fee = determine_customer_shipping_fee(margin_rate, list_price)

    if customer_fee == 0:
        return ("FREE", 0, 0)

    if margin_rate > 70:
        # 73%+: 조건부 6만원 무료배송
        return ("CONDITIONAL_FREE", DEFAULT_SHIPPING_COST, CONDITIONAL_FREE_THRESHOLD_73)

    if margin_rate > 67:
        # 68~70%: 조건부 3만원 무료배송
        return ("CONDITIONAL_FREE", customer_fee, CONDITIONAL_FREE_THRESHOLD_70)

    if margin_rate > 65:
        # 66~67%: 조건부 2.5만원 무료배송
        return ("CONDITIONAL_FREE", customer_fee, CONDITIONAL_FREE_THRESHOLD_67)

    # 그 외 (~65%): 조건부 2만원 무료배송
    return ("CONDITIONAL_FREE", customer_fee, CONDITIONAL_FREE_THRESHOLD)
