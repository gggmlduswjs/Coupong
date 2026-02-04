"""알라딘 API 크롤러 (공식 API)"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import requests
from typing import List, Dict, Optional
from datetime import datetime
import logging
from urllib.parse import quote

# Book 모델의 유틸리티 메서드 사용
from app.models.book import Book

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AladinAPICrawler:
    """
    알라딘 공식 API 크롤러

    API 문서: http://blog.aladin.co.kr/ttb/category/19154755
    """

    BASE_URL = "http://www.aladin.co.kr/ttb/api/"

    def __init__(self, ttb_key: str = None):
        """
        Args:
            ttb_key: 알라딘 TTBKey (발급 필요)
                    발급: https://www.aladin.co.kr/ttb/wblog_manage.aspx
        """
        self.ttb_key = ttb_key

        if not self.ttb_key:
            logger.warning("TTBKey가 없습니다. 발급받으세요: https://www.aladin.co.kr/ttb/wblog_manage.aspx")

        self.session = requests.Session()

    def search_by_keyword(
        self,
        keyword: str,
        max_results: int = 50,
        search_target: str = "Book"
    ) -> List[Dict]:
        """
        키워드로 도서 검색

        Args:
            keyword: 검색 키워드
            max_results: 최대 결과 수
            search_target: Book, Foreign, Music, DVD, Used, eBook

        Returns:
            도서 정보 리스트
        """
        if not self.ttb_key:
            logger.error("TTBKey가 필요합니다.")
            return []

        products = []
        start = 1
        max_per_page = 50  # API 최대값

        while len(products) < max_results:
            try:
                url = f"{self.BASE_URL}ItemSearch.aspx"

                params = {
                    "ttbkey": self.ttb_key,
                    "Query": keyword,
                    "QueryType": "Keyword",
                    "SearchTarget": search_target,
                    "Start": start,
                    "MaxResults": min(max_per_page, max_results - len(products)),
                    "output": "js",
                    "Version": "20131101"
                }

                logger.info(f"알라딘 API 요청: {keyword} (페이지 {start})")

                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()

                data = response.json()

                if "item" not in data or not data["item"]:
                    logger.info("더 이상 결과가 없습니다.")
                    break

                items = data["item"]

                for item in items:
                    product = self._parse_item(item)
                    if product:
                        products.append(product)
                        logger.info(f"수집: {product['title'][:40]}")

                if len(items) < max_per_page:
                    break

                start += len(items)

            except Exception as e:
                logger.error(f"API 요청 오류: {e}")
                break

        logger.info(f"알라딘 검색 완료: 총 {len(products)}개")
        return products

    def search_by_isbn(self, isbn: str) -> Optional[Dict]:
        """
        ISBN으로 도서 검색

        Args:
            isbn: ISBN-10 또는 ISBN-13

        Returns:
            도서 정보 또는 None
        """
        if not self.ttb_key:
            logger.error("TTBKey가 필요합니다.")
            return None

        try:
            url = f"{self.BASE_URL}ItemLookUp.aspx"

            params = {
                "ttbkey": self.ttb_key,
                "itemIdType": "ISBN",
                "ItemId": isbn,
                "output": "js",
                "Version": "20131101"
            }

            logger.info(f"알라딘 ISBN 검색: {isbn}")

            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            if "item" not in data or not data["item"]:
                logger.warning(f"ISBN {isbn}을 찾을 수 없습니다.")
                return None

            item = data["item"][0]
            product = self._parse_item(item)

            if product:
                logger.info(f"찾음: {product['title']}")

            return product

        except Exception as e:
            logger.error(f"ISBN 검색 오류: {e}")
            return None

    def _parse_item(self, item: Dict) -> Dict:
        """API 응답을 표준 형식으로 변환 (연도 추출 포함)"""
        try:
            # ISBN (13자리 우선, 없으면 10자리)
            isbn = item.get("isbn13", "") or item.get("isbn", "")

            # 제목
            title = item.get("title", "")

            # 연도 추출 (Book 모델의 메서드 사용)
            year = Book.extract_year(title)

            # 제목 정규화 (연도 제거)
            normalized_title = Book.normalize_title(title, year)

            # 시리즈명 추출 (묶음 SKU용)
            normalized_series = Book.extract_series(normalized_title)

            # 가격 (정가)
            price = item.get("priceSales", 0)  # 판매가
            if price == 0:
                price = item.get("priceStandard", 15000)  # 정가

            # 출간일
            pub_date = item.get("pubDate", "")
            publish_date = None
            if pub_date:
                try:
                    publish_date = datetime.strptime(pub_date, "%Y-%m-%d").date()
                except:
                    pass

            result = {
                "isbn": isbn,
                "title": title,
                "author": item.get("author", ""),
                "publisher": item.get("publisher", ""),
                "original_price": int(price),
                "category": item.get("categoryName", "도서"),
                "subcategory": "",
                "image_url": item.get("cover", ""),
                "description": item.get("description", ""),
                "kyobo_url": item.get("link", ""),  # 알라딘 링크
                "publish_date": publish_date,
                "crawled_at": datetime.utcnow(),

                # 연도 및 정규화 정보 (V2 추가)
                "year": year,
                "normalized_title": normalized_title,
                "normalized_series": normalized_series,

                # 추가 정보
                "page_count": item.get("subInfo", {}).get("itemPage", 0) if isinstance(item.get("subInfo"), dict) else 0,
            }

            # 로그에 연도 정보 포함
            if year:
                logger.debug(f"  Year extracted: {year} from '{title}'")
                logger.debug(f"  Normalized: '{normalized_title}'")
                logger.debug(f"  Series: '{normalized_series}'")

            return result

        except Exception as e:
            logger.error(f"아이템 파싱 오류: {e}")
            return None


# 테스트 함수
def test_with_sample_key():
    """샘플 TTBKey로 테스트 (실제로는 발급받은 키 사용)"""

    print("\n" + "="*60)
    print("알라딘 API 크롤러 테스트")
    print("="*60)

    # TTBKey 입력
    print("\n알라딘 TTBKey를 입력하세요.")
    print("발급: https://www.aladin.co.kr/ttb/wblog_manage.aspx")
    print("(Enter 키를 누르면 데모 모드로 실행)")

    ttb_key = input("\nTTBKey: ").strip()

    if not ttb_key:
        print("\n⚠️  TTBKey가 없습니다.")
        print("데모 데이터로 진행합니다.\n")
        demo_mode()
        return

    # 실제 API 테스트
    crawler = AladinAPICrawler(ttb_key=ttb_key)

    print("\n" + "="*60)
    print("1. 키워드 검색 테스트: '초등수학'")
    print("="*60)

    products = crawler.search_by_keyword("초등수학", max_results=5)

    if products:
        print(f"\n수집 완료: {len(products)}개\n")

        for i, p in enumerate(products, 1):
            print(f"{i}. {p['title'][:50]}")
            print(f"   저자: {p['author']}")
            print(f"   출판사: {p['publisher']}")
            print(f"   가격: {p['original_price']:,}원")
            print(f"   ISBN: {p['isbn']}")
            print()
    else:
        print("\n검색 결과가 없습니다.")

    print("\n" + "="*60)
    print("2. ISBN 검색 테스트")
    print("="*60)

    test_isbn = input("\nISBN을 입력하세요 (Enter=건너뛰기): ").strip()

    if test_isbn:
        product = crawler.search_by_isbn(test_isbn)

        if product:
            print(f"\n찾음!")
            print(f"제목: {product['title']}")
            print(f"저자: {product['author']}")
            print(f"출판사: {product['publisher']}")
            print(f"가격: {product['original_price']:,}원")
        else:
            print("\n찾을 수 없습니다.")


def demo_mode():
    """데모 모드 (TTBKey 없을 때)"""
    print("="*60)
    print("데모: 알라딘 API 사용 방법")
    print("="*60)

    print("\n1. TTBKey 발급받기:")
    print("   https://www.aladin.co.kr/ttb/wblog_manage.aspx")
    print("   → 알라딘 로그인")
    print("   → TTB 키 발급")

    print("\n2. 키 설정:")
    print("   .env 파일에 추가:")
    print("   ALADIN_TTB_KEY=your_key_here")

    print("\n3. 사용 예시:")
    print("""
from crawlers.aladin_api_crawler import AladinAPICrawler

# 초기화
crawler = AladinAPICrawler(ttb_key="your_key")

# 키워드 검색
products = crawler.search_by_keyword("초등수학", max_results=10)

# ISBN 검색
product = crawler.search_by_isbn("9788956746425")
    """)

    print("\n4. DB 저장:")
    print("   python scripts/aladin_to_db.py")

    print("\n5. CSV 생성:")
    print("   python scripts/generate_official_csv.py")


if __name__ == "__main__":
    test_with_sample_key()
