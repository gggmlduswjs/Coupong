"""Playwright 자동 업로더"""
from typing import Dict, List
from playwright.async_api import async_playwright, Page
from pathlib import Path
import time
import random
import logging
from app.config import settings

logger = logging.getLogger(__name__)


class PlaywrightUploader:
    """쿠팡 브라우저 자동화 업로더"""

    COUPANG_SELLER_URL = "https://wing.coupang.com"
    LOGIN_URL = f"{COUPANG_SELLER_URL}/login"
    PRODUCT_REGISTER_URL = f"{COUPANG_SELLER_URL}/tenants/vendor/product/registration"

    def __init__(self, account_id: int, session_dir: str = "sessions"):
        self.account_id = account_id
        self.session_file = f"{session_dir}/account_{account_id}.json"
        self.delay_min = settings.upload_delay_min
        self.delay_max = settings.upload_delay_max

    async def login(self, email: str, password: str) -> bool:
        """
        쿠팡 판매자센터 로그인

        Args:
            email: 계정 이메일
            password: 계정 비밀번호

        Returns:
            로그인 성공 여부
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)  # 보안을 위해 headless=False
            context = await browser.new_context()
            page = await context.new_page()

            try:
                logger.info(f"로그인 시도: {email}")
                await page.goto(self.LOGIN_URL)

                # 이메일 입력
                await page.fill("input[name='loginId']", email)
                await self._human_delay()

                # 비밀번호 입력
                await page.fill("input[name='password']", password)
                await self._human_delay()

                # 로그인 버튼 클릭
                await page.click("button[type='submit']")
                await page.wait_for_timeout(5000)

                # 로그인 성공 확인
                if "dashboard" in page.url or "home" in page.url:
                    logger.info("로그인 성공")

                    # 세션 저장
                    Path(self.session_file).parent.mkdir(parents=True, exist_ok=True)
                    await context.storage_state(path=self.session_file)

                    return True
                else:
                    logger.error("로그인 실패")
                    return False

            except Exception as e:
                logger.error(f"로그인 오류: {e}")
                return False
            finally:
                await browser.close()

    async def upload_product(self, product: Dict) -> Dict:
        """
        상품 자동 업로드

        Args:
            product: 상품 정보

        Returns:
            업로드 결과
        """
        # 세션 파일 확인
        if not Path(self.session_file).exists():
            raise FileNotFoundError(f"세션 파일 없음: {self.session_file}. 먼저 login() 실행 필요.")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(storage_state=self.session_file)
            page = await context.new_page()

            try:
                logger.info(f"상품 업로드 시작: {product['product_name'][:30]}...")

                # 상품 등록 페이지 이동
                await page.goto(self.PRODUCT_REGISTER_URL)
                await page.wait_for_timeout(3000)

                # 폼 입력
                await self._fill_product_form(page, product)

                # 등록 버튼 클릭
                await page.click("button[type='submit']")
                await page.wait_for_timeout(5000)

                # 성공 확인
                if "success" in page.url or await page.query_selector(".success-message"):
                    logger.info("업로드 성공")
                    return {
                        "success": True,
                        "product_id": product.get("id"),
                        "message": "업로드 완료"
                    }
                else:
                    logger.error("업로드 실패")
                    return {
                        "success": False,
                        "product_id": product.get("id"),
                        "message": "업로드 실패"
                    }

            except Exception as e:
                logger.error(f"업로드 오류: {e}")
                return {
                    "success": False,
                    "product_id": product.get("id"),
                    "message": str(e)
                }
            finally:
                await browser.close()

    async def _fill_product_form(self, page: Page, product: Dict):
        """상품 등록 폼 입력 (실제 쿠팡 페이지 구조에 맞게 수정 필요)"""

        # 상품명
        await page.fill("input[name='productName']", product["product_name"])
        await self._human_delay()

        # 판매가
        await page.fill("input[name='salePrice']", str(product["sale_price"]))
        await self._human_delay()

        # 정가
        await page.fill("input[name='originalPrice']", str(product["original_price"]))
        await self._human_delay()

        # ISBN
        if product.get("isbn"):
            await page.fill("input[name='isbn']", product["isbn"])
            await self._human_delay()

        # 이미지 업로드 (URL 또는 파일)
        if product.get("main_image_url"):
            # URL 방식 또는 다운로드 후 파일 업로드
            # 실제 구현 시 쿠팡 페이지에 맞게 조정
            pass

        # 상세 설명
        if product.get("description"):
            await page.fill("textarea[name='description']", product["description"])
            await self._human_delay()

    def _human_delay(self):
        """사람처럼 행동 (랜덤 딜레이)"""
        delay = random.uniform(self.delay_min, self.delay_max)
        time.sleep(delay)

    async def upload_batch(self, products: List[Dict]) -> List[Dict]:
        """
        여러 상품 일괄 업로드

        Args:
            products: 상품 정보 리스트

        Returns:
            업로드 결과 리스트
        """
        results = []
        max_daily = settings.upload_max_daily_per_account

        for i, product in enumerate(products):
            if i >= max_daily:
                logger.warning(f"일일 업로드 제한 도달: {max_daily}개")
                break

            result = await self.upload_product(product)
            results.append(result)

            # 상품 간 딜레이
            await self._human_delay()

        return results
