"""비즈니스 상수 - 매직넘버 중앙 관리"""

# 도서정가제 (한국 법률)
BOOK_DISCOUNT_RATE = 0.9  # 정가 × 0.9 = 판매가

# 쿠팡 수수료
COUPANG_FEE_RATE = 0.11  # 판매가의 11%

# 배송비
DEFAULT_SHIPPING_COST = 2000  # 기본 배송비 (원)
FREE_SHIPPING_THRESHOLD = 2000  # 무료배송 순마진 기준 (원)

# 재고
DEFAULT_STOCK = 10  # 기본 재고 수량
DEFAULT_LEAD_TIME = 2  # 출고 소요일

# API
API_THROTTLE_SECONDS = 1.0  # 알라딘 API 호출 간격 (초)
COUPANG_WING_RATE_LIMIT = 0.1  # WING API 호출 간격 (초, 10 calls/sec)

# 쿠팡 WING API - 도서 상품 등록 기본값 (PDF 가이드 기반)
BOOK_PRODUCT_DEFAULTS = {
    "deliveryMethod": "SEQUENCIAL",              # 일반배송
    "deliveryChargeType": "FREE",                # 무료배송 기본 (마진에 따라 변경)
    "deliveryCharge": 0,
    "freeShipOverAmount": 0,
    "deliveryChargeOnReturn": 2500,
    "unionDeliveryType": "UNION_DELIVERY",
    "remoteAreaDeliverable": "N",
    "returnChargeVendor": "N",
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
