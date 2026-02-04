"""베이스 크롤러"""
from abc import ABC, abstractmethod
from typing import List, Dict
import time
import random
from app.config import settings


class BaseCrawler(ABC):
    """크롤러 베이스 클래스"""

    def __init__(self):
        self.delay_min = settings.crawl_delay_min
        self.delay_max = settings.crawl_delay_max
        self.max_items = settings.crawl_max_items_per_session
        self.timeout = settings.crawl_timeout

    def wait(self):
        """랜덤 딜레이"""
        delay = random.uniform(self.delay_min, self.delay_max)
        time.sleep(delay)

    @abstractmethod
    async def crawl(self, category: str, limit: int) -> List[Dict]:
        """크롤링 실행 (하위 클래스에서 구현)"""
        pass

    def _clean_price(self, price_text: str) -> int:
        """가격 텍스트 정제"""
        # "12,000원" → 12000
        import re
        numbers = re.sub(r'[^\d]', '', price_text)
        return int(numbers) if numbers else 0

    def _clean_isbn(self, isbn_text: str) -> str:
        """ISBN 정제"""
        import re
        # ISBN 13자리만 추출
        numbers = re.sub(r'[^\d]', '', isbn_text)
        return numbers[:13] if len(numbers) >= 13 else numbers
