"""교보문고 크롤러"""
from typing import List, Dict
from playwright.async_api import async_playwright
from crawlers.base_crawler import BaseCrawler
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class KyoboCrawler(BaseCrawler):
    """교보문고 크롤러"""

    BASE_URL = "https://www.kyobobook.co.kr"

    async def crawl(self, category: str = "초등교재", limit: int = 50) -> List[Dict]:
        """
        교보문고 신간 크롤링

        Args:
            category: 검색 키워드
            limit: 최대 수집 개수

        Returns:
            상품 정보 리스트
        """
        products = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()

            try:
                # 검색 페이지 접속
                search_url = f"{self.BASE_URL}/search?keyword={category}&target=total"
                logger.info(f"크롤링 시작: {search_url}")
                await page.goto(search_url, timeout=self.timeout * 1000)

                # 도서 탭 클릭 (필요 시)
                await page.wait_for_timeout(2000)

                # 상품 목록 수집
                page_num = 1
                while len(products) < limit:
                    logger.info(f"페이지 {page_num} 크롤링 중...")

                    # 상품 아이템 추출
                    items = await page.query_selector_all(".prod_item")

                    if not items:
                        logger.warning("상품 아이템을 찾을 수 없습니다.")
                        break

                    for item in items:
                        if len(products) >= limit:
                            break

                        try:
                            product = await self._extract_product_info(item)
                            if product:
                                products.append(product)
                                logger.info(f"수집: {product['title'][:30]}...")
                        except Exception as e:
                            logger.error(f"상품 추출 오류: {e}")
                            continue

                        self.wait()

                    # 다음 페이지
                    next_button = await page.query_selector("a.btn_next")
                    if next_button and len(products) < limit:
                        await next_button.click()
                        await page.wait_for_timeout(2000)
                        page_num += 1
                    else:
                        break

            except Exception as e:
                logger.error(f"크롤링 오류: {e}")
                raise
            finally:
                await browser.close()

        logger.info(f"크롤링 완료: 총 {len(products)}개 수집")
        return products

    async def _extract_product_info(self, item) -> Dict:
        """상품 정보 추출"""
        try:
            # 제목
            title_elem = await item.query_selector(".prod_info .title a")
            title = await title_elem.inner_text() if title_elem else ""

            # 가격
            price_elem = await item.query_selector(".prod_price .val")
            price_text = await price_elem.inner_text() if price_elem else "0"
            price = self._clean_price(price_text)

            # ISBN
            isbn = await item.get_attribute("data-isbn") or ""
            isbn = self._clean_isbn(isbn)

            # 저자
            author_elem = await item.query_selector(".prod_info .author")
            author = await author_elem.inner_text() if author_elem else ""

            # 출판사
            publisher_elem = await item.query_selector(".prod_info .publisher")
            publisher = await publisher_elem.inner_text() if publisher_elem else ""

            # 이미지
            img_elem = await item.query_selector(".prod_thumb img")
            image_url = await img_elem.get_attribute("src") if img_elem else ""

            # 상품 URL
            link_elem = await item.query_selector(".prod_info .title a")
            product_url = await link_elem.get_attribute("href") if link_elem else ""
            if product_url and not product_url.startswith("http"):
                product_url = self.BASE_URL + product_url

            # 출간일 (상세 페이지에서만 가능, 일단 None)
            publish_date = None

            return {
                "isbn": isbn,
                "title": title.strip(),
                "author": author.strip(),
                "publisher": publisher.strip(),
                "original_price": price,
                "category": "교재",  # 검색 키워드 기반
                "subcategory": "",
                "image_url": image_url,
                "description": "",  # 상세 페이지에서만 가능
                "kyobo_url": product_url,
                "publish_date": publish_date,
                "crawled_at": datetime.utcnow()
            }

        except Exception as e:
            logger.error(f"상품 정보 추출 오류: {e}")
            return None
