"""교보문고 크롤러 V2 (수정 버전)"""
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
if __name__ == "__main__":
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))

from typing import List, Dict
from playwright.async_api import async_playwright
from crawlers.base_crawler import BaseCrawler
from datetime import datetime
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KyoboCrawlerV2(BaseCrawler):
    """교보문고 크롤러 V2 (실제 작동 버전)"""

    BASE_URL = "https://www.kyobobook.co.kr"

    async def crawl(self, keyword: str = "초등교재", limit: int = 50) -> List[Dict]:
        """
        교보문고 검색 크롤링

        Args:
            keyword: 검색 키워드
            limit: 최대 수집 개수

        Returns:
            상품 정보 리스트
        """
        products = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,  # 브라우저 표시
                args=['--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080}
            )
            page = await context.new_page()

            try:
                # 검색 페이지
                url = f"{self.BASE_URL}/search?keyword={keyword}&target=total"
                logger.info(f"크롤링 시작: {url}")

                await page.goto(url, timeout=60000)
                logger.info("페이지 로드 완료. 콘텐츠 대기 중...")

                # 동적 콘텐츠 로딩 대기 (10초)
                await page.wait_for_timeout(10000)

                # 스크롤해서 lazy loading 트리거
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

                # 상품 요소 찾기
                # 교보문고는 [class*='prod'] 또는 이미지 링크로 찾을 수 있음
                product_links = await page.query_selector_all("a[href*='/product/']")
                logger.info(f"상품 링크 발견: {len(product_links)}개")

                if not product_links:
                    logger.warning("상품 링크를 찾을 수 없습니다.")
                    # 대체 방법: 이미지에서 찾기
                    images = await page.query_selector_all("img[alt]")
                    logger.info(f"대체 방법: 이미지 {len(images)}개 발견")

                    for img in images[:limit]:
                        try:
                            product = await self._extract_from_image(page, img)
                            if product and product.get("title"):
                                products.append(product)
                                logger.info(f"수집: {product['title'][:30]}")

                                if len(products) >= limit:
                                    break
                        except Exception as e:
                            logger.error(f"이미지 추출 오류: {e}")
                            continue

                else:
                    # 링크에서 정보 추출
                    for link in product_links[:limit * 2]:  # 여유있게 더 많이 확인
                        if len(products) >= limit:
                            break

                        try:
                            product = await self._extract_from_link(page, link)
                            if product and product.get("title"):
                                products.append(product)
                                logger.info(f"수집: {product['title'][:40]}")
                        except Exception as e:
                            logger.error(f"링크 추출 오류: {e}")
                            continue

                        self.wait()

            except Exception as e:
                logger.error(f"크롤링 오류: {e}")
                raise

            finally:
                await browser.close()

        logger.info(f"크롤링 완료: 총 {len(products)}개 수집")
        return products

    async def _extract_from_link(self, page, link) -> Dict:
        """링크 요소에서 상품 정보 추출"""
        try:
            # 링크 URL
            href = await link.get_attribute("href")
            if not href:
                return None

            # 전체 URL 생성
            if href.startswith("/"):
                product_url = self.BASE_URL + href
            else:
                product_url = href

            # 부모 요소에서 정보 찾기
            parent = link

            # 제목 (링크 텍스트 또는 alt)
            title = await link.inner_text()
            if not title or len(title) < 3:
                # 이미지 alt에서 찾기
                img = await link.query_selector("img")
                if img:
                    title = await img.get_attribute("alt")

            if not title or len(title) < 3:
                return None

            # 이미지
            img = await link.query_selector("img")
            image_url = ""
            if img:
                image_url = await img.get_attribute("src")

            # 가격 찾기 (부모 요소에서)
            # 여러 단계 위로 올라가면서 가격 찾기
            price = 0
            for i in range(5):  # 최대 5단계 위까지
                try:
                    parent_elem = await parent.evaluate_handle("el => el.parentElement")
                    if parent_elem:
                        parent = parent_elem.as_element()
                        # 가격 텍스트 찾기
                        price_text = await parent.inner_text()

                        # 숫자 + "원" 패턴 찾기
                        price_match = re.search(r'(\d{1,3}(?:,\d{3})*)\s*원', price_text)
                        if price_match:
                            price = self._clean_price(price_match.group(1))
                            break
                except:
                    break

            # ISBN 추출 (URL에서)
            isbn = ""
            isbn_match = re.search(r'/product/(\d{10,13})', product_url)
            if isbn_match:
                isbn = isbn_match.group(1)

            return {
                "isbn": isbn,
                "title": title.strip(),
                "author": "",  # 상세 페이지 필요
                "publisher": "",  # 상세 페이지 필요
                "original_price": price if price > 0 else 15000,  # 기본값
                "category": "교재",
                "subcategory": "",
                "image_url": image_url,
                "description": "",
                "kyobo_url": product_url,
                "publish_date": None,
                "crawled_at": datetime.utcnow()
            }

        except Exception as e:
            logger.error(f"링크 정보 추출 오류: {e}")
            return None

    async def _extract_from_image(self, page, img) -> Dict:
        """이미지 요소에서 상품 정보 추출"""
        try:
            # 제목 (alt)
            title = await img.get_attribute("alt")
            if not title or len(title) < 3:
                return None

            # 이미지 URL
            image_url = await img.get_attribute("src")

            # 부모 링크 찾기
            parent_link = await img.evaluate_handle(
                "el => el.closest('a[href*=\"/product/\"]')"
            )

            product_url = ""
            isbn = ""

            if parent_link:
                href = await parent_link.as_element().get_attribute("href")
                if href:
                    if href.startswith("/"):
                        product_url = self.BASE_URL + href
                    else:
                        product_url = href

                    # ISBN 추출
                    isbn_match = re.search(r'/product/(\d{10,13})', product_url)
                    if isbn_match:
                        isbn = isbn_match.group(1)

            return {
                "isbn": isbn,
                "title": title.strip(),
                "author": "",
                "publisher": "",
                "original_price": 15000,  # 기본값
                "category": "교재",
                "subcategory": "",
                "image_url": image_url,
                "description": "",
                "kyobo_url": product_url,
                "publish_date": None,
                "crawled_at": datetime.utcnow()
            }

        except Exception as e:
            logger.error(f"이미지 정보 추출 오류: {e}")
            return None


# 테스트
async def test_crawler():
    """크롤러 테스트"""
    crawler = KyoboCrawlerV2()

    print("\n" + "="*60)
    print("교보문고 크롤러 V2 테스트")
    print("="*60)

    products = await crawler.crawl(keyword="초등수학", limit=10)

    print(f"\n수집 완료: {len(products)}개\n")

    for i, p in enumerate(products, 1):
        print(f"{i}. {p['title'][:50]}")
        print(f"   가격: {p['original_price']:,}원")
        print(f"   ISBN: {p['isbn']}")
        print(f"   이미지: {p['image_url'][:50]}...")
        print(f"   URL: {p['kyobo_url'][:50]}...")
        print()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_crawler())
