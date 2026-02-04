"""쿠팡 공식 템플릿에 맞춘 CSV 생성기"""
import pandas as pd
from pathlib import Path
from typing import List, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class CoupangCSVGenerator:
    """쿠팡 공식 템플릿 기반 CSV 생성"""

    def __init__(self, output_dir: str = "data/uploads"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_csv(
        self,
        products: List[Dict],
        account_name: str = "default"
    ) -> str:
        """
        쿠팡 공식 템플릿 형식의 CSV 생성

        Args:
            products: 상품 정보 리스트
            account_name: 계정 이름

        Returns:
            생성된 CSV 파일 경로
        """
        rows = []

        for product in products:
            row = self._create_template_row(product)
            rows.append(row)

        df = pd.DataFrame(rows)

        # 파일명 생성
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"coupang_official_{account_name}_{timestamp}.csv"
        filepath = self.output_dir / filename

        # CSV 저장 (UTF-8 BOM)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")

        logger.info(f"CSV 생성: {filepath} ({len(rows)}개 상품)")
        return str(filepath)

    def _create_template_row(self, product: Dict) -> Dict:
        """
        쿠팡 공식 템플릿 행 생성

        도서 카테고리 기준 필수 컬럼
        """
        return {
            # 기본정보 (필수)
            "카테고리": "도서",
            "등록상품명": product.get("product_name", ""),
            "판매시작일": "",  # 비워두면 내일
            "판매종료일": "",  # 비워두면 2099-12-31
            "상품상태": "새상품",
            "상태설명": "",
            "브랜드": product.get("publisher", "기타"),
            "제조사": product.get("publisher", "기타"),
            "검색어": self._generate_keywords(product),

            # 구매옵션 (도서는 단일상품이므로 비워둠)
            "옵션유형1": "",
            "옵션값1": "",
            "옵션유형2": "",
            "옵션값2": "",
            "옵션유형3": "",
            "옵션값3": "",
            "옵션유형4": "",
            "옵션값4": "",
            "옵션유형5": "",
            "옵션값5": "",
            "옵션유형6": "",
            "옵션값6": "",

            # 검색옵션 (도서 카테고리 기준)
            "검색옵션_옵션유형1": "",
            "검색옵션_옵션값1": "",
            # ... (20개까지 있지만 도서는 대부분 불필요)

            # 구성정보 (필수)
            "판매가격": product.get("sale_price", 0),
            "할인율기준가": product.get("original_price", 0),
            "재고수량": 10,
            "출고리드타임": 2,  # 2일
            "인당최대구매수량": 0,  # 제한없음
            "최대구매수량기간(일)": 1,
            "성인상품(19)": "N",
            "과세여부": "Y",
            "병행수입여부": "N",
            "해외구매대행": "N",
            "업체상품코드": product.get("isbn", ""),
            "모델번호": "",
            "바코드": product.get("isbn", ""),

            # 인증정보 (도서는 인증대상아님)
            "인증∙신고 등 정보유형": "인증대상아님",
            "인증∙신고 등 정보값": "",
            "인증∙이동통신 사전승낙서 또는 인증대리점 인증서": "",
            "인증∙판매점 사전승낙 인증마크 또는 이동통신사 대리점 인증마크": "",

            # 주문 추가메시지
            "주문 추가메시지": "",

            # 상품고시정보 (도서 필수)
            "상품고시정보 카테고리": "도서",
            "상품고시정보값1": product.get("product_name", ""),  # 도서명
            "상품고시정보값2": f"{product.get('author', '저자미상')} / {product.get('publisher', '')}",  # 저자/출판사
            "상품고시정보값3": "상세페이지 참조",  # 크기(페이지수)
            "상품고시정보값4": "",  # 출간일
            "상품고시정보값5": "도서",  # 구성
            "상품고시정보값6": product.get("description", ""),  # 목차 또는 책소개
            "상품고시정보값7": "",
            "상품고시정보값8": "",
            "상품고시정보값9": "",
            "상품고시정보값10": "",
            "상품고시정보값11": "",
            "상품고시정보값12": "",
            "상품고시정보값13": "",
            "상품고시정보값14": "",

            # 이미지 (필수)
            "대표(옵션)이미지": product.get("main_image_url", ""),
            "추가이미지": "",  # 쉼표로 구분
            "상태이미지(중고상품)": "",

            # 상세설명 (필수)
            "상세 설명": self._generate_detail_description(product),

            # 구비서류
            "구비서류값1": "",
            "구비서류값2": "",
            "구비서류값3": "",
            "구비서류값4": "",
            "구비서류값5": "",
            "구비서류값6": "",
            "구비서류값7": "",
        }

    def _generate_keywords(self, product: Dict) -> str:
        """검색어 생성 (/ 구분, 최대 20개)"""
        keywords = []

        # 제목에서 키워드 추출
        title = product.get("product_name", "")
        if "초등" in title:
            keywords.extend(["초등", "초등학생", "초등교재"])
        if "중등" in title:
            keywords.extend(["중등", "중학생", "중등교재"])
        if "수학" in title:
            keywords.extend(["수학", "수학문제집", "수학교재"])
        if "국어" in title:
            keywords.extend(["국어", "국어문제집", "독해력"])
        if "영어" in title:
            keywords.extend(["영어", "영어문법", "영어교재"])

        # 학년
        for grade in ["1학년", "2학년", "3학년", "4학년", "5학년", "6학년"]:
            if grade in title:
                keywords.append(grade)

        # 출판사
        if product.get("publisher"):
            keywords.append(product["publisher"])

        # 중복 제거 및 최대 20개
        keywords = list(dict.fromkeys(keywords))[:20]

        return "/".join(keywords)

    def _generate_detail_description(self, product: Dict) -> str:
        """
        상세 설명 생성

        주의: 실제로는 이미지 파일명을 쉼표로 구분해서 입력
        텍스트 설명이 아님!
        """
        # 실제로는 이미지 URL 또는 업로드된 파일명을 입력해야 함
        # 예: "detail_image_1.jpg,detail_image_2.jpg"

        # 임시로 이미지 URL 사용
        if product.get("main_image_url"):
            return product["main_image_url"]

        return ""

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


# 테스트 함수
def test_generate():
    """테스트 CSV 생성"""
    test_products = [
        {
            "product_name": "초등 수학 문제집 3학년 1학기 [10% 할인]",
            "original_price": 15000,
            "sale_price": 13500,
            "isbn": "9788956746425",
            "publisher": "천재교육",
            "author": "교육연구소",
            "main_image_url": "https://contents.kyobobook.co.kr/sih/fit-in/458x0/pdt/123456789.jpg",
            "description": "3학년 1학기 수학 전 과정을 체계적으로 학습할 수 있는 문제집입니다."
        },
    ]

    generator = CoupangCSVGenerator()
    accounts = ["account_1", "account_2", "account_3", "account_4", "account_5"]

    result = generator.generate_batch_csvs(test_products, accounts)

    print("=" * 60)
    print("쿠팡 공식 템플릿 CSV 생성 완료")
    print("=" * 60)
    for account, filepath in result.items():
        print(f"{account}: {filepath}")


if __name__ == "__main__":
    test_generate()
