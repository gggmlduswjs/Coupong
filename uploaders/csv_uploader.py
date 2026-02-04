"""CSV 업로더"""
import pandas as pd
from pathlib import Path
from typing import List, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class CSVUploader:
    """쿠팡 CSV 대량등록 파일 생성"""

    def __init__(self, output_dir: str = "data/uploads"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_csv(
        self,
        products: List[Dict],
        account_name: str = "default"
    ) -> str:
        """
        쿠팡 대량등록 CSV 파일 생성

        Args:
            products: 상품 정보 리스트
            account_name: 계정 이름

        Returns:
            생성된 CSV 파일 경로
        """
        rows = []

        for product in products:
            row = self._create_csv_row(product)
            rows.append(row)

        df = pd.DataFrame(rows)

        # 파일명 생성
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"coupang_upload_{account_name}_{timestamp}.csv"
        filepath = self.output_dir / filename

        # CSV 저장 (UTF-8 BOM 인코딩)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")

        logger.info(f"CSV 파일 생성: {filepath} ({len(rows)}개 상품)")
        return str(filepath)

    def _create_csv_row(self, product: Dict) -> Dict:
        """
        쿠팡 CSV 행 생성

        쿠팡 대량등록 템플릿 컬럼:
        - 상품명, 판매가, 정가, 카테고리, 상품코드(ISBN), 출판사,
        - 대표이미지, 상세이미지, 배송방식, 재고수량, 등
        """
        return {
            "상품명": product.get("product_name", ""),
            "판매가": product.get("sale_price", 0),
            "정가": product.get("original_price", 0),
            "카테고리": product.get("category", "도서/교재"),
            "상품코드": product.get("isbn", ""),
            "출판사": product.get("publisher", ""),
            "저자": product.get("author", ""),
            "대표이미지": product.get("main_image_url", ""),
            "상세설명": product.get("description", ""),
            "배송방식": "무료배송",
            "배송비": 0,
            "재고수량": 10,
            "판매상태": "판매중",
            "ISBN": product.get("isbn", ""),
        }

    def generate_batch_csvs(
        self,
        products: List[Dict],
        accounts: List[str]
    ) -> Dict[str, str]:
        """
        여러 계정용 CSV 일괄 생성

        Args:
            products: 상품 정보 리스트
            accounts: 계정 이름 리스트

        Returns:
            {account_name: csv_filepath}
        """
        result = {}

        for account_name in accounts:
            filepath = self.generate_csv(products, account_name)
            result[account_name] = filepath

        logger.info(f"일괄 CSV 생성 완료: {len(accounts)}개 계정")
        return result
