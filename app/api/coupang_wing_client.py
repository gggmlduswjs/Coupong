"""
쿠팡 WING Open API 클라이언트
==============================
HMAC-SHA256 인증, Rate Limit(10/sec) 준수, 주요 엔드포인트 지원

사용법:
    client = CoupangWingClient(vendor_id="A00317195", access_key="...", secret_key="...")
    products = client.list_products()
    product = client.get_product(seller_product_id=12345)
"""
import time
import hmac
import hashlib
import urllib.parse
from datetime import datetime, timezone
import logging
from typing import Optional, Dict, Any, List

import requests

logger = logging.getLogger(__name__)

# 재시도 설정
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # 초
RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)


class CoupangWingError(Exception):
    """쿠팡 WING API 오류"""
    def __init__(self, code: str, message: str, status_code: int = 0):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"[{code}] {message}")


class CoupangWingClient:
    """쿠팡 WING Open API 클라이언트"""

    BASE_URL = "https://api-gateway.coupang.com"
    RATE_LIMIT_INTERVAL = 0.1  # 10 calls/sec → 최소 0.1초 간격

    # 엔드포인트 경로
    SELLER_PRODUCTS_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
    VENDOR_ITEMS_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items"
    CATEGORY_PREDICT_PATH = "/v2/providers/openapi/apis/api/v1/categorization/predict"
    DISPLAY_CATEGORIES_PATH = "/v2/providers/openapi/apis/api/v1/products/display-categories"
    CATEGORY_META_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/meta/category-related-metas/display-category-codes"
    SELLER_AUTO_GEN_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/seller/auto-generated"

    def __init__(self, vendor_id: str, access_key: str, secret_key: str):
        self.vendor_id = vendor_id
        self.access_key = access_key
        self.secret_key = secret_key
        self._last_request_time = 0.0
        self._session = requests.Session()

    def _generate_hmac(self, method: str, path: str, query: str = "") -> str:
        """
        HMAC-SHA256 서명 생성

        서명 대상 문자열:
            {datetime}\n{method}\n{path}\n{query}

        Returns:
            Authorization 헤더 값
        """
        dt = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
        message = f"{dt}{method}{path}{query}"

        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return f"CEA algorithm=HmacSHA256, access-key={self.access_key}, signed-date={dt}, signature={signature}"

    def _throttle(self):
        """Rate limit 준수: 요청 간 최소 0.1초 간격"""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.RATE_LIMIT_INTERVAL:
            time.sleep(self.RATE_LIMIT_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        timeout: int = 30,
        retry: bool = True,
    ) -> Dict[str, Any]:
        """
        공통 API 요청 (재시도 로직 포함)

        Args:
            method: HTTP 메서드 (GET, POST, PUT, DELETE)
            path: API 경로
            params: 쿼리 파라미터
            data: 요청 바디 (JSON)
            timeout: 요청 타임아웃 (초)
            retry: 재시도 활성화 여부

        Returns:
            API 응답 JSON

        Raises:
            CoupangWingError: API 오류 발생 시
        """
        max_attempts = MAX_RETRIES if retry else 1
        last_error = None

        for attempt in range(1, max_attempts + 1):
            self._throttle()

            # 쿼리 스트링 구성 (순서 유지 - 쿠팡 API는 원본 순서 사용)
            query = ""
            if params:
                query = "&".join(f"{k}={v}" for k, v in params.items())

            # HMAC 서명 생성
            authorization = self._generate_hmac(method.upper(), path, query)

            url = f"{self.BASE_URL}{path}"
            if query:
                url = f"{url}?{query}"

            headers = {
                "Authorization": authorization,
                "Content-Type": "application/json;charset=UTF-8",
                "X-EXTENDED-TIMEOUT": "90000",
            }

            logger.debug(f"WING API {method} {path} params={params} (시도 {attempt}/{max_attempts})")

            try:
                response = self._session.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    json=data,
                    timeout=timeout,
                )

                # 재시도 가능한 상태 코드 확인
                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt < max_attempts:
                        delay = self._calculate_retry_delay(attempt)
                        logger.warning(
                            f"재시도 가능 상태 {response.status_code}, "
                            f"{delay:.1f}초 후 재시도 ({attempt}/{max_attempts})"
                        )
                        time.sleep(delay)
                        continue

                # 응답 처리
                if response.status_code == 200:
                    return self._parse_response(response)

                # 오류 처리
                try:
                    error_body = response.json()
                    code = error_body.get("code", str(response.status_code))
                    message = error_body.get("message", response.text)
                except ValueError:
                    code = str(response.status_code)
                    message = response.text

                raise CoupangWingError(code, message, response.status_code)

            except requests.exceptions.ConnectionError as e:
                last_error = CoupangWingError("NETWORK_ERROR", f"연결 오류: {e}")
                if attempt < max_attempts:
                    delay = self._calculate_retry_delay(attempt)
                    logger.warning(f"연결 오류, {delay:.1f}초 후 재시도 ({attempt}/{max_attempts}): {e}")
                    time.sleep(delay)
                    continue
                raise last_error

            except requests.exceptions.Timeout as e:
                last_error = CoupangWingError("TIMEOUT", f"타임아웃: {e}")
                if attempt < max_attempts:
                    delay = self._calculate_retry_delay(attempt)
                    logger.warning(f"타임아웃, {delay:.1f}초 후 재시도 ({attempt}/{max_attempts})")
                    time.sleep(delay)
                    continue
                raise last_error

            except requests.RequestException as e:
                raise CoupangWingError("NETWORK_ERROR", f"요청 실패: {e}")

        # 모든 재시도 소진
        if last_error:
            raise last_error
        raise CoupangWingError("MAX_RETRIES", "최대 재시도 횟수 초과")

    def _calculate_retry_delay(self, attempt: int) -> float:
        """지수 백오프 대기 시간 계산"""
        import random
        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
        # ±25% 지터 추가
        jitter = delay * 0.25 * random.uniform(-1, 1)
        return min(delay + jitter, 30.0)  # 최대 30초

    def _parse_response(self, response: requests.Response) -> Dict[str, Any]:
        """
        API 응답 파싱 (중첩 구조 안전 처리)

        Args:
            response: requests 응답 객체

        Returns:
            파싱된 JSON 딕셔너리
        """
        try:
            result = response.json()
        except ValueError:
            return {"data": response.text}

        # 쿠팡 API는 HTTP 200에서도 에러를 반환할 수 있음
        if isinstance(result, dict):
            code = result.get("code", "")
            if code == "ERROR":
                message = result.get("message", "알 수 없는 오류")
                raise CoupangWingError("API_ERROR", message)

        return result

    # ─────────────────────────────────────────────
    # 상품 관리
    # ─────────────────────────────────────────────

    def get_product(self, seller_product_id: int) -> Dict[str, Any]:
        """
        상품 단건 조회

        Args:
            seller_product_id: 쿠팡 판매자 상품 ID

        Returns:
            상품 상세 정보
        """
        path = f"{self.SELLER_PRODUCTS_PATH}/{seller_product_id}"
        return self._request("GET", path)

    def list_products(self, max_per_page: int = 50, max_pages: int = 0) -> List[Dict]:
        """
        전체 상품 목록 조회 (nextToken 자동 페이징)

        Args:
            max_per_page: 페이지당 최대 상품 수 (최대 100)
            max_pages: 최대 페이지 수 (0=무제한)

        Returns:
            전체 상품 리스트
        """
        all_products = []
        next_token = ""
        page = 0

        while True:
            params = {
                "vendorId": self.vendor_id,
                "maxPerPage": str(max_per_page),
            }
            if next_token:
                params["nextToken"] = next_token

            path = f"{self.SELLER_PRODUCTS_PATH}"
            result = self._request("GET", path, params=params)

            data = result.get("data", [])
            if isinstance(data, list):
                all_products.extend(data)
            elif isinstance(data, dict):
                products = data.get("products", data.get("items", []))
                all_products.extend(products)

            # 다음 페이지 토큰 확인
            next_token = result.get("nextToken", "")
            if not next_token:
                # data가 dict인 경우 내부에서 확인
                if isinstance(data, dict):
                    next_token = data.get("nextToken", "")

            page += 1
            logger.info(f"  페이지 {page}: {len(data) if isinstance(data, list) else len(products)}개 로드 (누적 {len(all_products)}개)")

            if not next_token:
                break
            if max_pages > 0 and page >= max_pages:
                logger.info(f"  최대 페이지({max_pages}) 도달, 중단")
                break

        return all_products

    def create_product(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        상품 등록

        Args:
            product_data: 상품 등록 JSON 데이터

        Returns:
            등록 결과 (sellerProductId 포함)
        """
        return self._request("POST", self.SELLER_PRODUCTS_PATH, data=product_data)

    def update_product(self, seller_product_id: int, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        상품 수정 (승인 필요)

        Args:
            seller_product_id: 수정할 상품 ID
            product_data: 수정 데이터

        Returns:
            수정 결과
        """
        path = f"{self.SELLER_PRODUCTS_PATH}/{seller_product_id}"
        return self._request("PUT", path, data=product_data)

    def patch_product(self, seller_product_id: int, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        상품 수정 (승인 불필요) - 배송비, 반품비 등 일부 필드만 변경

        Args:
            seller_product_id: 수정할 상품 ID
            product_data: 수정 데이터 (변경할 필드만)

        Returns:
            수정 결과
        """
        path = f"{self.SELLER_PRODUCTS_PATH}/{seller_product_id}"
        return self._request("PATCH", path, data=product_data)

    def delete_product(self, seller_product_id: int) -> Dict[str, Any]:
        """
        상품 삭제 (판매중지)

        Args:
            seller_product_id: 삭제할 상품 ID

        Returns:
            삭제 결과
        """
        path = f"{self.SELLER_PRODUCTS_PATH}/{seller_product_id}"
        return self._request("DELETE", path)

    def get_inflow_status(self) -> Dict[str, Any]:
        """
        상품 등록 현황 조회

        Returns:
            등록 현황 (전체/승인대기/승인완료/반려 등 카운트)
        """
        path = f"{self.SELLER_PRODUCTS_PATH}/inflow-status"
        return self._request("GET", path)

    def get_product_partial(self, seller_product_id: int) -> Dict[str, Any]:
        """
        상품 조회 (승인 불필요 항목만)

        Args:
            seller_product_id: 상품 ID

        Returns:
            승인 불필요 항목 상세 정보
        """
        path = f"{self.SELLER_PRODUCTS_PATH}/{seller_product_id}/partial"
        return self._request("GET", path)

    def approve_product(self, seller_product_id: int) -> Dict[str, Any]:
        """
        상품 승인 요청

        Args:
            seller_product_id: 승인 요청할 상품 ID

        Returns:
            승인 요청 결과
        """
        path = f"{self.SELLER_PRODUCTS_PATH}/{seller_product_id}/approve"
        return self._request("PUT", path)

    def list_products_by_timeframe(
        self,
        vendor_id: str,
        created_at_from: str,
        created_at_to: str,
        max_per_page: int = 50,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        상품 목록 구간 조회 (생성일 기준)

        Args:
            vendor_id: 벤더 ID
            created_at_from: 시작일시 (ISO 8601, 예: 2026-01-01T00:00:00)
            created_at_to: 종료일시 (ISO 8601)
            max_per_page: 페이지당 상품 수 (최대 100)
            status: 상품 상태 필터 (옵션)

        Returns:
            상품 목록 + 페이징 정보
        """
        path = f"{self.SELLER_PRODUCTS_PATH}/by-timeframe"
        params = {
            "vendorId": vendor_id,
            "createdAtFrom": created_at_from,
            "createdAtTo": created_at_to,
            "maxPerPage": str(max_per_page),
        }
        if status:
            params["status"] = status
        return self._request("GET", path, params=params)

    def get_product_history(
        self,
        seller_product_id: int,
        next_token: Optional[str] = None,
        max_per_page: int = 10,
    ) -> Dict[str, Any]:
        """
        상품 상태변경이력 조회

        Args:
            seller_product_id: 상품 ID
            next_token: 페이징 토큰
            max_per_page: 페이지당 건수 (기본 10)

        Returns:
            상태변경 이력 목록
        """
        path = f"{self.SELLER_PRODUCTS_PATH}/{seller_product_id}/histories"
        params = {"maxPerPage": str(max_per_page)}
        if next_token:
            params["nextToken"] = next_token
        return self._request("GET", path, params=params)

    def get_product_by_sku(self, external_vendor_sku_code: str) -> Dict[str, Any]:
        """
        SKU 코드로 상품 요약 정보 조회

        Args:
            external_vendor_sku_code: 외부 벤더 SKU 코드

        Returns:
            상품 요약 정보
        """
        path = f"{self.VENDOR_ITEMS_PATH}/external-vendor-sku-codes/{external_vendor_sku_code}"
        return self._request("GET", path)

    def stop_sale(self, vendor_item_id: int) -> Dict[str, Any]:
        """(deprecated: stop_item_sale 사용 권장) 아이템별 판매 중지"""
        return self.stop_item_sale(vendor_item_id)

    # ─────────────────────────────────────────────
    # 재고/가격 관리
    # ─────────────────────────────────────────────

    def update_price(self, vendor_item_id: int, new_price: int, force: bool = True) -> Dict[str, Any]:
        """
        옵션별 가격 변경

        Args:
            vendor_item_id: 벤더 아이템 ID
            new_price: 새 판매가 (10원 단위)
            force: 가격 변경 비율 제한 해제 (기본 True)
                   - False: 기존 가격 대비 최대 50% 인하 / 100% 인상까지만 가능
                   - True: 제한 없이 변경 가능

        Returns:
            업데이트 결과
        """
        path = f"{self.VENDOR_ITEMS_PATH}/{vendor_item_id}/prices/{new_price}"
        params = {"forceSalePriceUpdate": "true"} if force else None
        return self._request("PUT", path, params=params)

    def update_quantity(self, vendor_item_id: int, quantity: int) -> Dict[str, Any]:
        """
        옵션별 재고 변경

        Args:
            vendor_item_id: 벤더 아이템 ID
            quantity: 재고 수량

        Returns:
            업데이트 결과
        """
        path = f"{self.VENDOR_ITEMS_PATH}/{vendor_item_id}/quantities/{quantity}"
        return self._request("PUT", path)

    def update_inventory(self, vendor_item_id: int, quantity: int, price: int) -> Dict[str, Any]:
        """
        재고/가격 동시 업데이트 (deprecated - update_price, update_quantity 사용 권장)

        Args:
            vendor_item_id: 벤더 아이템 ID
            quantity: 재고 수량
            price: 판매가

        Returns:
            업데이트 결과
        """
        # 가격 먼저, 재고 다음
        price_result = self.update_price(vendor_item_id, price)
        quantity_result = self.update_quantity(vendor_item_id, quantity)
        return {"price": price_result, "quantity": quantity_result}

    def get_item_inventory(self, vendor_item_id: int) -> Dict[str, Any]:
        """
        아이템별 수량/가격/상태 조회

        Args:
            vendor_item_id: 벤더 아이템 ID

        Returns:
            아이템 재고/가격/판매상태 정보
        """
        path = f"{self.VENDOR_ITEMS_PATH}/{vendor_item_id}/inventories"
        return self._request("GET", path)

    def update_original_price(self, vendor_item_id: int, original_price: int) -> Dict[str, Any]:
        """
        아이템별 할인율 기준가격 변경

        Args:
            vendor_item_id: 벤더 아이템 ID
            original_price: 할인율 기준가격 (원래가격)

        Returns:
            변경 결과
        """
        path = f"{self.VENDOR_ITEMS_PATH}/{vendor_item_id}/original-prices/{original_price}"
        return self._request("PUT", path)

    def stop_item_sale(self, vendor_item_id: int) -> Dict[str, Any]:
        """
        아이템별 판매 중지

        Args:
            vendor_item_id: 벤더 아이템 ID

        Returns:
            중지 결과
        """
        path = f"{self.VENDOR_ITEMS_PATH}/{vendor_item_id}/sales/stop"
        return self._request("PUT", path)

    def resume_item_sale(self, vendor_item_id: int) -> Dict[str, Any]:
        """
        아이템별 판매 재개

        Args:
            vendor_item_id: 벤더 아이템 ID

        Returns:
            재개 결과
        """
        path = f"{self.VENDOR_ITEMS_PATH}/{vendor_item_id}/sales/resume"
        return self._request("PUT", path)

    # ─────────────────────────────────────────────
    # 자동생성옵션
    # ─────────────────────────────────────────────

    def enable_auto_option(self, vendor_item_id: int) -> Dict[str, Any]:
        """
        자동생성옵션 활성화 (단일 옵션)

        Args:
            vendor_item_id: 벤더 아이템 ID

        Returns:
            활성화 결과
        """
        path = f"{self.SELLER_AUTO_GEN_PATH}/{vendor_item_id}/enable"
        return self._request("POST", path)

    def enable_auto_option_all(self) -> Dict[str, Any]:
        """
        자동생성옵션 활성화 (전체)

        Returns:
            전체 활성화 결과
        """
        path = f"{self.SELLER_AUTO_GEN_PATH}/enable-all"
        return self._request("POST", path)

    def disable_auto_option(self, vendor_item_id: int) -> Dict[str, Any]:
        """
        자동생성옵션 비활성화 (단일 옵션)

        Args:
            vendor_item_id: 벤더 아이템 ID

        Returns:
            비활성화 결과
        """
        path = f"{self.SELLER_AUTO_GEN_PATH}/{vendor_item_id}/disable"
        return self._request("POST", path)

    def disable_auto_option_all(self) -> Dict[str, Any]:
        """
        자동생성옵션 비활성화 (전체)

        Returns:
            전체 비활성화 결과
        """
        path = f"{self.SELLER_AUTO_GEN_PATH}/disable-all"
        return self._request("POST", path)

    # ─────────────────────────────────────────────
    # 카테고리
    # ─────────────────────────────────────────────

    def recommend_category(self, product_name: str, brand: Optional[str] = None) -> Dict[str, Any]:
        """
        카테고리 추천 (상품명 기반)

        Args:
            product_name: 상품명
            brand: 브랜드명 (옵션)

        Returns:
            추천 카테고리 정보
        """
        data = {"productName": product_name}
        if brand:
            data["brand"] = brand
        return self._request("POST", self.CATEGORY_PREDICT_PATH, data=data)

    def get_category_meta(self, display_category_code: str) -> Dict[str, Any]:
        """
        카테고리 메타 정보 조회 (필수 속성, 고시정보 등)

        Args:
            display_category_code: 디스플레이 카테고리 코드

        Returns:
            카테고리 메타 정보
        """
        path = f"{self.CATEGORY_META_PATH}/{display_category_code}"
        return self._request("GET", path)

    def get_display_categories(self, display_category_code: str) -> Dict[str, Any]:
        """
        디스플레이 카테고리 조회

        Args:
            display_category_code: 카테고리 코드

        Returns:
            카테고리 정보
        """
        path = f"{self.DISPLAY_CATEGORIES_PATH}/{display_category_code}"
        return self._request("GET", path)

    # ─────────────────────────────────────────────
    # 물류 (출고지/반품지)
    # ─────────────────────────────────────────────

    def get_outbound_shipping_places(self, page_num: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """출고지 목록 조회 (marketplace v1 - GET)"""
        path = "/v2/providers/marketplace_openapi/apis/api/v1/vendor/shipping-place/outbound"
        params = {"pageNum": str(page_num), "pageSize": str(page_size)}
        return self._request("GET", path, params=params)

    def get_return_shipping_centers(self, page_num: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """반품지 목록 조회 (openapi v4 - GET)"""
        path = f"/v2/providers/openapi/apis/api/v4/vendors/{self.vendor_id}/returnShippingCenters"
        params = {"pageNum": str(page_num), "pageSize": str(page_size)}
        return self._request("GET", path, params=params)

    def create_outbound_shipping_place(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """출고지 생성 (v5 - POST)"""
        path = f"/v2/providers/openapi/apis/api/v5/vendors/{self.vendor_id}/outboundShippingCenters"
        return self._request("POST", path, data=data)

    def create_return_shipping_center(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """반품지 생성 (v5 - POST)"""
        path = f"/v2/providers/openapi/apis/api/v5/vendors/{self.vendor_id}/returnShippingCenters"
        return self._request("POST", path, data=data)

    # ─────────────────────────────────────────────
    # 발주서/매출
    # ─────────────────────────────────────────────

    def get_ordersheets(self, created_at_from: str, created_at_to: str, status: str = "ACCEPT") -> Dict[str, Any]:
        """
        발주서 조회

        Args:
            created_at_from: 시작일시 (ISO 8601)
            created_at_to: 종료일시 (ISO 8601)
            status: 발주 상태 (ACCEPT, INSTRUCT, DEPARTURE, DELIVERY 등)

        Returns:
            발주서 목록
        """
        path = f"/v2/providers/openapi/apis/api/v5/vendors/{self.vendor_id}/ordersheets"
        params = {
            "createdAtFrom": created_at_from,
            "createdAtTo": created_at_to,
            "status": status,
        }
        return self._request("GET", path, params=params)

    # ─────────────────────────────────────────────
    # 매출 내역
    # ─────────────────────────────────────────────

    def get_revenue_history(self, date_from: str, date_to: str,
                            token: str = "", max_per_page: int = 50) -> Dict[str, Any]:
        """
        매출 내역 단일 페이지 조회

        Args:
            date_from: 인식일 시작 (YYYY-MM-DD)
            date_to: 인식일 종료 (YYYY-MM-DD)
            token: 페이징 토큰
            max_per_page: 페이지당 최대 건수

        Returns:
            매출 내역 응답 (data, hasNext, nextToken)
        """
        path = "/v2/providers/openapi/apis/api/v1/revenue-history"
        params = {
            "vendorId": self.vendor_id,
            "recognitionDateFrom": date_from,
            "recognitionDateTo": date_to,
            "token": token,
            "maxPerPage": str(max_per_page),
        }
        return self._request("GET", path, params=params)

    def get_all_revenue_history(self, date_from: str, date_to: str) -> List[Dict]:
        """
        매출 내역 전체 조회 (자동 페이징)

        Args:
            date_from: 인식일 시작 (YYYY-MM-DD)
            date_to: 인식일 종료 (YYYY-MM-DD)

        Returns:
            전체 매출 내역 리스트 (주문 단위)
        """
        all_data = []
        token = ""
        page = 0
        while True:
            result = self.get_revenue_history(date_from, date_to, token=token)
            data = result.get("data", [])
            if isinstance(data, list):
                all_data.extend(data)
            elif isinstance(data, dict):
                items = data.get("orderItems", data.get("items", []))
                all_data.extend(items)
            page += 1
            logger.info(f"  매출 내역 페이지 {page}: {len(data) if isinstance(data, list) else '?'}건")

            if not result.get("hasNext", False):
                break
            token = result.get("nextToken", "")
            if not token:
                break
        return all_data

    # ─────────────────────────────────────────────
    # 정산 내역
    # ─────────────────────────────────────────────

    SETTLEMENT_HISTORY_PATH = "/v2/providers/marketplace_openapi/apis/api/v1/settlement-histories"

    def get_settlement_history(self, year_month: str) -> List[Dict]:
        """
        정산 내역 조회

        Args:
            year_month: 매출인식 기간 (YYYY-MM)

        Returns:
            정산 내역 리스트
        """
        params = {"revenueRecognitionYearMonth": year_month}
        result = self._request("GET", self.SETTLEMENT_HISTORY_PATH, params=params)

        # API가 리스트를 직접 반환할 수 있음
        if isinstance(result, list):
            return result
        # dict인 경우 data 키 확인
        data = result.get("data", result)
        if isinstance(data, list):
            return data
        return [data] if data else []

    # ─────────────────────────────────────────────
    # 연결 테스트
    # ─────────────────────────────────────────────

    def test_connection(self) -> bool:
        """
        API 연결 테스트 (상품 목록 1개 조회로 확인)

        Returns:
            True: 연결 성공, False: 실패
        """
        try:
            params = {"vendorId": self.vendor_id, "maxPerPage": "1"}
            result = self._request("GET", self.SELLER_PRODUCTS_PATH, params=params)
            logger.info(f"WING API 연결 성공: vendor_id={self.vendor_id}")
            return True
        except CoupangWingError as e:
            logger.error(f"WING API 연결 실패: vendor_id={self.vendor_id}, {e}")
            return False

    def __repr__(self):
        return f"<CoupangWingClient(vendor_id='{self.vendor_id}')>"
