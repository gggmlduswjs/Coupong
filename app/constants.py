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
