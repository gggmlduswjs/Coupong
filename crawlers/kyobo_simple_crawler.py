"""교보문고 간단 크롤러 (requests + BeautifulSoup)"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import requests
from bs4 import BeautifulSoup
from typing import List, Dict
from datetime import datetime
import re
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KyoboSimpleCrawler:
    """교보문고 간단 크롤러"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        })

    def crawl(self, keyword: str = "초등교재", limit: int = 50) -> List[Dict]:
        """
        교보문고 검색 크롤링

        Args:
            keyword: 검색 키워드
            limit: 최대 수집 개수

        Returns:
            상품 정보 리스트
        """
        products = []
        page = 1

        while len(products) < limit:
            logger.info(f"페이지 {page} 크롤링 중...")

            url = f"https://www.kyobobook.co.kr/search?keyword={keyword}&gbCode=TOT&target=total&page={page}"

            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, 'html.parser')

                # 상품 추출 시도
                extracted = self._extract_products(soup)

                if not extracted:
                    logger.warning(f"페이지 {page}에서 상품을 찾을 수 없습니다.")
                    break

                for product in extracted:
                    if len(products) >= limit:
                        break
                    products.append(product)
                    logger.info(f"수집: {product['title'][:40]}")

                if len(extracted) == 0:
                    break

                page += 1
                time.sleep(2)  # 요청 간 딜레이

            except Exception as e:
                logger.error(f"크롤링 오류: {e}")
                break

        logger.info(f"크롤링 완료: 총 {len(products)}개 수집")
        return products

    def _extract_products(self, soup: BeautifulSoup) -> List[Dict]:
        """HTML에서 상품 정보 추출"""
        products = []

        # 여러 가능한 선택자 시도
        selectors = [
            'div.prod_item',
            'div.product_item',
            'li.prod_item',
            'li.product',
            'div[class*="prod"]',
            'div[class*="product"]',
        ]

        items = []
        for selector in selectors:
            items = soup.select(selector)
            if items:
                logger.info(f"선택자 '{selector}'로 {len(items)}개 발견")
                break

        if not items:
            # 대체 방법: 모든 링크에서 /product/ 찾기
            links = soup.find_all('a', href=re.compile(r'/product/\d+'))
            logger.info(f"대체 방법: {len(links)}개 상품 링크 발견")

            for link in links:
                try:
                    product = self._extract_from_link(link)
                    if product:
                        products.append(product)
                except:
                    continue

            return products

        # 일반적인 추출
        for item in items:
            try:
                product = self._extract_from_item(item)
                if product:
                    products.append(product)
            except Exception as e:
                logger.error(f"상품 추출 오류: {e}")
                continue

        return products

    def _extract_from_item(self, item) -> Dict:
        """상품 아이템에서 정보 추출"""
        # 제목
        title_elem = item.select_one('a.prod_info, a.title, .prod_name')
        title = title_elem.get_text(strip=True) if title_elem else ""

        # 가격
        price_elem = item.select_one('.price .val, .prod_price, [class*="price"]')
        price = 0
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            price = self._clean_price(price_text)

        # 이미지
        img_elem = item.select_one('img')
        image_url = ""
        if img_elem:
            image_url = img_elem.get('src', '') or img_elem.get('data-src', '')

        # URL
        link_elem = item.select_one('a[href*="/product/"]')
        product_url = ""
        isbn = ""
        if link_elem:
            href = link_elem.get('href', '')
            if href.startswith('/'):
                product_url = f"https://www.kyobobook.co.kr{href}"
            else:
                product_url = href

            # ISBN 추출
            isbn_match = re.search(r'/product/(\d{10,13})', product_url)
            if isbn_match:
                isbn = isbn_match.group(1)

        return {
            "isbn": isbn,
            "title": title,
            "author": "",
            "publisher": "",
            "original_price": price if price > 0 else 15000,
            "category": "교재",
            "subcategory": "",
            "image_url": image_url,
            "description": "",
            "kyobo_url": product_url,
            "publish_date": None,
            "crawled_at": datetime.utcnow()
        }

    def _extract_from_link(self, link) -> Dict:
        """링크 요소에서 정보 추출"""
        # 제목
        title = link.get_text(strip=True)

        # URL
        href = link.get('href', '')
        if href.startswith('/'):
            product_url = f"https://www.kyobobook.co.kr{href}"
        else:
            product_url = href

        # ISBN
        isbn = ""
        isbn_match = re.search(r'/product/(\d{10,13})', product_url)
        if isbn_match:
            isbn = isbn_match.group(1)

        if not title or len(title) < 3:
            return None

        return {
            "isbn": isbn,
            "title": title,
            "author": "",
            "publisher": "",
            "original_price": 15000,
            "category": "교재",
            "subcategory": "",
            "image_url": "",
            "description": "",
            "kyobo_url": product_url,
            "publish_date": None,
            "crawled_at": datetime.utcnow()
        }

    def _clean_price(self, price_text: str) -> int:
        """가격 텍스트 정제"""
        numbers = re.sub(r'[^\d]', '', price_text)
        return int(numbers) if numbers else 0


# 테스트
def test():
    """크롤러 테스트"""
    crawler = KyoboSimpleCrawler()

    print("\n" + "="*60)
    print("교보문고 간단 크롤러 테스트")
    print("="*60)

    products = crawler.crawl(keyword="초등수학", limit=10)

    print(f"\n수집 완료: {len(products)}개\n")

    for i, p in enumerate(products, 1):
        print(f"{i}. {p['title'][:50]}")
        print(f"   가격: {p['original_price']:,}원")
        print(f"   ISBN: {p['isbn']}")
        print(f"   URL: {p['kyobo_url'][:60]}...")
        print()


if __name__ == "__main__":
    test()
