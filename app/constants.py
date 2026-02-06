"""비즈니스 상수 - 매직넘버 중앙 관리"""

# 도서정가제 (한국 법률)
BOOK_DISCOUNT_RATE = 0.9  # 정가 × 0.9 = 판매가

# 쿠팡 수수료
COUPANG_FEE_RATE = 0.11  # 판매가의 11%

# 배송비
DEFAULT_SHIPPING_COST = 2300  # 실제 택배비 (원)
FREE_SHIPPING_THRESHOLD = 2000  # 무료배송 순마진 기준 (원) - 마진 2000원 이상이면 무료배송 가능
TARGET_MARGIN_MIN = 1300  # 목표 최소 마진 (원)
TARGET_MARGIN_MAX = 2000  # 목표 최대 마진 (원)

# 재고
DEFAULT_STOCK = 10  # 기본 재고 수량
DEFAULT_LEAD_TIME = 2  # 출고 소요일
LOW_STOCK_THRESHOLD = 3  # 재고 부족 기준 (이하면 리필)

# API
API_THROTTLE_SECONDS = 1.0  # 알라딘 API 호출 간격 (초)
COUPANG_WING_RATE_LIMIT = 0.1  # WING API 호출 간격 (초, 10 calls/sec)

# 쿠팡 WING API - 도서 상품 등록 기본값 (PDF 가이드 기반)
# 마진 계산: 순마진 = 정가×0.151 + (고객배송비 - 실제배송비)
# 유료배송(2,500원)이면 +200원, 무료배송이면 -2,300원
BOOK_PRODUCT_DEFAULTS = {
    "deliveryMethod": "SEQUENCIAL",              # 일반배송
    "deliveryChargeType": "NOT_FREE",            # 유료배송 기본
    "deliveryCharge": 2500,                       # 고객 부담 배송비 (실제 2,300원 + 200원 마진)
    "freeShipOverAmount": 0,                      # 조건부 무료배송 금액 (0=사용안함)
    "deliveryChargeOnReturn": 2500,
    "unionDeliveryType": "UNION_DELIVERY",
    "remoteAreaDeliverable": "N",
    "returnCharge": 2500,
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
# 가격/마진 설정
# ─────────────────────────────────────────────
PRICE_CONFIG = {
    "min_margin": 1300,         # 최소 마진 (원) - 이 이하면 판매 비권장
    "target_margin": 2000,      # 목표 마진 (원)
    "min_margin_rate": 0.05,    # 최소 마진율 (5%)
    "bundle_threshold": 2000,   # 묶음 판매 기준 마진 (원)
}
