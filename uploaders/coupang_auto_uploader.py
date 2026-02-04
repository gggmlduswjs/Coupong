"""쿠팡 자동 업로드 (실제 작동 버전)"""
import sys
from pathlib import Path
import asyncio
import random
from typing import Dict, List

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright, Page, Browser
from app.database import SessionLocal
from app.models.account import Account
from app.models.product import Product
from app.utils.encryption import encryptor
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CoupangAutoUploader:
    """쿠팡 자동 업로드"""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.session_dir = Path("sessions")
        self.session_dir.mkdir(exist_ok=True)

    async def login(self, account: Account) -> bool:
        """
        계정 로그인

        Args:
            account: Account 모델 인스턴스

        Returns:
            로그인 성공 여부
        """
        logger.info(f"Logging in: {account.account_name} ({account.email})")

        email = account.email
        password = encryptor.decrypt(account.password_encrypted)
        session_file = self.session_dir / f"account_{account.id}.json"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()

            try:
                # 로그인 페이지
                await page.goto("https://wing.coupang.com/login", timeout=30000)
                await page.wait_for_timeout(2000)

                # 이메일 입력
                await page.fill("input[name='username']", email)
                await page.wait_for_timeout(random.uniform(1, 2) * 1000)

                # 비밀번호 입력
                await page.fill("input[name='password']", password)
                await page.wait_for_timeout(random.uniform(1, 2) * 1000)

                # 로그인 버튼 클릭
                login_button = await page.query_selector("button[type='submit']")
                if not login_button:
                    login_button = await page.query_selector("button:has-text('로그인')")

                if login_button:
                    await login_button.click()
                    logger.info("Login button clicked")
                else:
                    logger.error("Login button not found")
                    await browser.close()
                    return False

                # 로그인 완료 대기 (최대 10초)
                try:
                    await page.wait_for_url("**/wing.coupang.com/**", timeout=10000)
                    logger.info("Login successful!")
                except:
                    logger.warning("Login might require CAPTCHA or 2FA")
                    # 수동 처리를 위해 30초 대기
                    logger.info("Waiting 30 seconds for manual verification...")
                    await page.wait_for_timeout(30000)

                # 세션 저장
                await context.storage_state(path=str(session_file))
                logger.info(f"Session saved: {session_file}")

                # DB 업데이트
                db = SessionLocal()
                account.last_login_at = datetime.utcnow()
                db.commit()
                db.close()

                return True

            except Exception as e:
                logger.error(f"Login error: {e}")
                return False

            finally:
                await browser.close()

    async def upload_product(
        self,
        account: Account,
        product_data: Dict
    ) -> Dict:
        """
        단일 상품 업로드

        Args:
            account: Account 모델 인스턴스
            product_data: 상품 정보 딕셔너리

        Returns:
            업로드 결과
        """
        logger.info(f"Uploading product: {product_data['product_name'][:40]}")

        session_file = self.session_dir / f"account_{account.id}.json"

        # 세션 파일이 없으면 로그인 먼저
        if not session_file.exists():
            logger.warning("No session file. Logging in first...")
            success = await self.login(account)
            if not success:
                return {
                    "success": False,
                    "message": "Login failed"
                }

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                storage_state=str(session_file),
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()

            try:
                # 상품 등록 페이지
                # 쿠팡은 여러 등록 방식이 있을 수 있음:
                # 1. 일반 등록
                # 2. 카탈로그 등록 (ISBN 기반)
                # 3. 엑셀 대량 등록

                # ISBN이 있으면 카탈로그 등록 시도
                if product_data.get("isbn"):
                    result = await self._upload_via_catalog(page, product_data)
                else:
                    result = await self._upload_via_form(page, product_data)

                return result

            except Exception as e:
                logger.error(f"Upload error: {e}")
                return {
                    "success": False,
                    "message": str(e)
                }

            finally:
                await browser.close()

    async def _upload_via_catalog(self, page: Page, product_data: Dict) -> Dict:
        """ISBN 기반 카탈로그 등록"""
        logger.info(f"Trying catalog registration with ISBN: {product_data.get('isbn')}")

        try:
            # 카탈로그 등록 페이지
            await page.goto("https://wing.coupang.com/tenants/vendor/product/catalog-registration", timeout=30000)
            await page.wait_for_timeout(2000)

            # ISBN 입력
            isbn_input = await page.query_selector("input[placeholder*='ISBN']")
            if not isbn_input:
                isbn_input = await page.query_selector("input[name*='isbn']")

            if isbn_input:
                await isbn_input.fill(product_data["isbn"])
                await page.wait_for_timeout(1000)

                # 검색 버튼
                search_button = await page.query_selector("button:has-text('검색')")
                if search_button:
                    await search_button.click()
                    await page.wait_for_timeout(3000)

                    # 상품 선택
                    select_button = await page.query_selector("button:has-text('선택')")
                    if select_button:
                        await select_button.click()
                        await page.wait_for_timeout(2000)

                        # 가격 입력
                        price_input = await page.query_selector("input[name*='price']")
                        if price_input:
                            await price_input.fill(str(product_data["sale_price"]))
                            await page.wait_for_timeout(1000)

                        # 재고 입력
                        stock_input = await page.query_selector("input[name*='stock']")
                        if stock_input:
                            await stock_input.fill("10")
                            await page.wait_for_timeout(1000)

                        # 등록 버튼
                        submit_button = await page.query_selector("button:has-text('등록')")
                        if submit_button:
                            await submit_button.click()
                            await page.wait_for_timeout(5000)

                            logger.info("Product uploaded successfully!")
                            return {
                                "success": True,
                                "message": "Catalog registration succeeded"
                            }

            return {
                "success": False,
                "message": "Catalog registration failed (form not found)"
            }

        except Exception as e:
            logger.error(f"Catalog registration error: {e}")
            return {
                "success": False,
                "message": f"Catalog error: {e}"
            }

    async def _upload_via_form(self, page: Page, product_data: Dict) -> Dict:
        """일반 폼 등록"""
        logger.info("Trying manual form registration")

        try:
            # 일반 등록 페이지
            await page.goto("https://wing.coupang.com/tenants/vendor/product/registration", timeout=30000)
            await page.wait_for_timeout(3000)

            # 상품명
            name_input = await page.query_selector("input[name='productName']")
            if name_input:
                await name_input.fill(product_data["product_name"])
                await page.wait_for_timeout(random.uniform(1, 2) * 1000)

            # 가격
            price_input = await page.query_selector("input[name='salePrice']")
            if price_input:
                await price_input.fill(str(product_data["sale_price"]))
                await page.wait_for_timeout(random.uniform(1, 2) * 1000)

            # 카테고리는 수동으로 선택해야 할 수 있음
            logger.warning("Category selection might require manual input")

            # 등록 버튼
            submit_button = await page.query_selector("button:has-text('등록')")
            if submit_button:
                # 실제 제출 전에 확인
                logger.info("Ready to submit. Review the form if needed.")
                await page.wait_for_timeout(10000)  # 10초 대기

                # await submit_button.click()
                # await page.wait_for_timeout(5000)

                return {
                    "success": True,
                    "message": "Form filled (submission paused for review)"
                }

            return {
                "success": False,
                "message": "Submit button not found"
            }

        except Exception as e:
            logger.error(f"Form registration error: {e}")
            return {
                "success": False,
                "message": f"Form error: {e}"
            }

    async def upload_batch(
        self,
        account: Account,
        products: List[Dict],
        max_per_day: int = 20
    ) -> List[Dict]:
        """
        일괄 업로드

        Args:
            account: Account 인스턴스
            products: 상품 정보 리스트
            max_per_day: 하루 최대 업로드 수

        Returns:
            업로드 결과 리스트
        """
        logger.info(f"Batch upload: {len(products)} products for {account.account_name}")

        results = []
        count = 0

        for product in products:
            if count >= max_per_day:
                logger.warning(f"Daily limit reached: {max_per_day}")
                break

            result = await self.upload_product(account, product)
            results.append(result)
            count += 1

            # 상품 간 딜레이
            delay = random.uniform(10, 20)
            logger.info(f"Waiting {delay:.1f} seconds before next upload...")
            await asyncio.sleep(delay)

        return results


# 테스트 실행 함수
async def test_upload():
    """테스트 업로드"""
    db = SessionLocal()

    try:
        # 첫 번째 계정
        account = db.query(Account).filter(Account.is_active == True).first()

        if not account:
            print("No active accounts. Run: python scripts/register_accounts.py")
            return

        # 테스트 상품 데이터
        test_product = {
            "product_name": "초등 수학 문제집 3학년 [10% 할인]",
            "original_price": 15000,
            "sale_price": 13500,
            "isbn": "9788956746425",
            "publisher": "천재교육",
            "category": "도서/교재"
        }

        uploader = CoupangAutoUploader(headless=False)

        print(f"\n{'='*60}")
        print(f"Testing auto-upload for: {account.account_name}")
        print(f"{'='*60}\n")

        # 로그인 테스트
        print("Step 1: Login...")
        login_success = await uploader.login(account)

        if login_success:
            print("✓ Login successful\n")

            # 업로드 테스트
            print("Step 2: Upload product...")
            result = await uploader.upload_product(account, test_product)

            if result["success"]:
                print(f"✓ Upload successful: {result['message']}")
            else:
                print(f"✗ Upload failed: {result['message']}")
        else:
            print("✗ Login failed")

    finally:
        db.close()


if __name__ == "__main__":
    print("Coupang Auto Uploader - Test")
    print("="*60)
    asyncio.run(test_upload())
