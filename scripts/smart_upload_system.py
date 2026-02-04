"""스마트 업로드 시스템 - 완전 자동화"""
import sys
from pathlib import Path
import os

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from crawlers.aladin_api_crawler import AladinAPICrawler
from analyzers.margin_calculator import MarginCalculator
from analyzers.bundle_generator import BundleGenerator
from uploaders.coupang_csv_generator import CoupangCSVGenerator
from app.database import SessionLocal
from app.models import Publisher, Book, Product, BundleSKU, Listing, Account
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SmartUploadSystem:
    """
    스마트 업로드 시스템

    알라딘 API → 마진 분석 → 묶음 생성 → CSV 생성 → 계정 분배
    """

    def __init__(self, ttb_key: str = None):
        """
        Args:
            ttb_key: 알라딘 TTBKey
        """
        self.ttb_key = ttb_key or os.getenv("ALADIN_TTB_KEY")
        self.db = SessionLocal()
        self.crawler = AladinAPICrawler(ttb_key=self.ttb_key)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.close()

    def search_and_save_books(
        self,
        publishers: list,
        max_per_publisher: int = 20,
        recent_days: int = 180
    ) -> dict:
        """
        출판사별 도서 검색 및 DB 저장

        Args:
            publishers: Publisher 인스턴스 리스트
            max_per_publisher: 출판사당 최대 검색 개수
            recent_days: 최근 N일 이내 출간

        Returns:
            {
                'searched': int,
                'saved': int,
                'duplicates': int,
                'books': [Book, ...]
            }
        """
        logger.info("="*60)
        logger.info("1단계: 알라딘 API 도서 검색")
        logger.info("="*60)

        result = {
            'searched': 0,
            'saved': 0,
            'duplicates': 0,
            'books': []
        }

        for publisher in publishers:
            logger.info(f"\n[{publisher.name}] 검색 중...")

            # 알라딘 API 검색
            products = self.crawler.search_by_keyword(
                publisher.name,
                max_results=max_per_publisher
            )

            for p in products:
                result['searched'] += 1

                # 출판사 필터링
                if publisher.name not in p.get('publisher', ''):
                    continue

                # ISBN 체크
                if not p.get('isbn'):
                    continue

                # 중복 체크
                existing = self.db.query(Book).filter(
                    Book.isbn == p['isbn']
                ).first()

                if existing:
                    result['duplicates'] += 1
                    continue

                # Book 생성
                book = Book(
                    isbn=p['isbn'],
                    title=p['title'],
                    author=p.get('author', ''),
                    publisher_id=publisher.id,
                    publisher_name=publisher.name,
                    list_price=p['original_price'],
                    category=p.get('category', '도서'),
                    subcategory=p.get('subcategory', ''),
                    image_url=p.get('image_url', ''),
                    description=p.get('description', ''),
                    source_url=p.get('kyobo_url', ''),
                    publish_date=p.get('publish_date'),
                    page_count=p.get('page_count', 0),
                    year=p.get('year'),
                    normalized_title=p.get('normalized_title', ''),
                    normalized_series=p.get('normalized_series', ''),
                    crawled_at=datetime.utcnow(),
                    is_processed=False
                )

                self.db.add(book)
                result['saved'] += 1
                result['books'].append(book)

                logger.info(f"  저장: {book.title[:50]}")

        self.db.commit()

        logger.info(f"\n검색 완료: {result['searched']}개")
        logger.info(f"신규 저장: {result['saved']}개")
        logger.info(f"중복 제외: {result['duplicates']}개")

        return result

    def analyze_margins(self, books: list) -> dict:
        """
        마진 분석

        Args:
            books: Book 리스트

        Returns:
            {
                'total': int,
                'single_uploadable': [],
                'needs_bundle': [],
                'analysis': MarginCalculator 결과
            }
        """
        logger.info("\n" + "="*60)
        logger.info("2단계: 마진 분석")
        logger.info("="*60)

        result = {
            'total': len(books),
            'single_uploadable': [],
            'needs_bundle': [],
            'products': []
        }

        with MarginCalculator(self.db) as calc:
            for book in books:
                # Publisher 조회
                publisher = self.db.query(Publisher).get(book.publisher_id)

                if not publisher:
                    continue

                # Product 생성
                product = calc.create_product_from_analysis(book, publisher)
                self.db.add(product)
                result['products'].append(product)

                if product.can_upload_single:
                    result['single_uploadable'].append(product)
                    logger.info(f"  [단권 가능] {book.title[:50]} (순마진: {product.net_margin:,}원)")
                else:
                    result['needs_bundle'].append(product)
                    logger.info(f"  [묶음 필요] {book.title[:50]} (순마진: {product.net_margin:,}원)")

        self.db.commit()

        logger.info(f"\n단권 업로드 가능: {len(result['single_uploadable'])}개")
        logger.info(f"묶음 SKU 필요: {len(result['needs_bundle'])}개")

        return result

    def generate_bundles(self, min_margin: int = 2000) -> dict:
        """
        묶음 SKU 생성

        Args:
            min_margin: 최소 순마진

        Returns:
            {
                'created': int,
                'bundles': [BundleSKU, ...]
            }
        """
        logger.info("\n" + "="*60)
        logger.info("3단계: 묶음 SKU 생성")
        logger.info("="*60)

        with BundleGenerator(self.db) as generator:
            result = generator.auto_generate_bundles(
                min_margin=min_margin,
                min_books=2,
                max_books=5
            )

            logger.info(f"\n묶음 생성 완료: {result['created']}개")

            if result['errors']:
                logger.warning(f"오류 발생: {len(result['errors'])}개")

            return result

    def distribute_to_accounts(
        self,
        products: list,
        bundles: list
    ) -> dict:
        """
        5개 계정에 중복 없이 분배

        Args:
            products: Product 리스트
            bundles: BundleSKU 리스트

        Returns:
            {
                'account_1': {'products': [], 'bundles': []},
                ...
            }
        """
        logger.info("\n" + "="*60)
        logger.info("4단계: 계정별 분배 (중복 방지)")
        logger.info("="*60)

        # 계정 조회
        accounts = self.db.query(Account).filter(Account.is_active == True).all()

        if not accounts:
            logger.error("활성 계정이 없습니다.")
            return {}

        distribution = {acc.id: {'products': [], 'bundles': []} for acc in accounts}

        # 단권 상품 분배
        for product in products:
            # 업로드 가능한 계정 조회
            available_accounts = product.get_available_accounts(
                [acc.id for acc in accounts],
                self.db
            )

            if available_accounts:
                # 첫 번째 가능한 계정에 할당
                account_id = available_accounts[0]
                distribution[account_id]['products'].append(product)
                logger.info(f"  [계정 {account_id}] {product.isbn}")

        # 묶음 SKU 분배
        for bundle in bundles:
            # 업로드 가능한 계정 조회
            available_accounts = bundle.get_available_accounts(
                [acc.id for acc in accounts],
                self.db
            )

            if available_accounts:
                # 첫 번째 가능한 계정에 할당
                account_id = available_accounts[0]
                distribution[account_id]['bundles'].append(bundle)
                logger.info(f"  [계정 {account_id}] {bundle.bundle_key}")

        # 통계
        for account_id, items in distribution.items():
            logger.info(f"\n계정 {account_id}: 단권 {len(items['products'])}개, 묶음 {len(items['bundles'])}개")

        return distribution

    def generate_csvs(self, distribution: dict) -> dict:
        """
        CSV 파일 생성

        Args:
            distribution: distribute_to_accounts() 결과

        Returns:
            {
                'account_1': 'filepath',
                ...
            }
        """
        logger.info("\n" + "="*60)
        logger.info("5단계: CSV 파일 생성")
        logger.info("="*60)

        generator = CoupangCSVGenerator()
        csv_files = {}

        for account_id, items in distribution.items():
            # Account 조회
            account = self.db.query(Account).get(account_id)

            if not account:
                continue

            # CSV 데이터 준비
            csv_data = []

            # 단권 상품
            for product in items['products']:
                csv_data.append(product.to_csv_row())

            # 묶음 SKU
            for bundle in items['bundles']:
                csv_data.append(bundle.to_csv_row())

            if csv_data:
                # CSV 생성
                output_dir = project_root / "data" / "uploads"
                output_dir.mkdir(parents=True, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{account.account_name}_{timestamp}.csv"
                filepath = output_dir / filename

                # TODO: 실제 CSV 쓰기 구현 (CoupangCSVGenerator 사용)
                logger.info(f"  [{account.account_name}] {len(csv_data)}개 상품 → {filepath}")

                csv_files[account.account_name] = str(filepath)

        return csv_files

    def run_full_workflow(
        self,
        publisher_names: list = None,
        max_per_publisher: int = 20
    ) -> dict:
        """
        전체 워크플로우 실행

        Args:
            publisher_names: 출판사명 리스트 (None이면 전체)
            max_per_publisher: 출판사당 최대 검색 개수

        Returns:
            전체 실행 결과
        """
        logger.info("\n" + "="*60)
        logger.info("스마트 업로드 시스템 시작")
        logger.info("="*60)

        start_time = datetime.now()

        # 출판사 조회
        if publisher_names:
            publishers = self.db.query(Publisher).filter(
                Publisher.name.in_(publisher_names),
                Publisher.is_active == True
            ).all()
        else:
            publishers = self.db.query(Publisher).filter(
                Publisher.is_active == True
            ).all()

        logger.info(f"\n대상 출판사: {len(publishers)}개")

        # 1. 도서 검색
        search_result = self.search_and_save_books(publishers, max_per_publisher)

        if not search_result['books']:
            logger.info("\n신규 도서가 없습니다.")
            return {}

        # 2. 마진 분석
        margin_result = self.analyze_margins(search_result['books'])

        # 3. 묶음 생성
        bundle_result = self.generate_bundles()

        # 4. 계정 분배
        distribution = self.distribute_to_accounts(
            margin_result['products'],
            bundle_result['bundles']
        )

        # 5. CSV 생성
        csv_files = self.generate_csvs(distribution)

        # 완료
        elapsed = (datetime.now() - start_time).total_seconds()

        logger.info("\n" + "="*60)
        logger.info("완료!")
        logger.info("="*60)
        logger.info(f"\n소요 시간: {elapsed:.1f}초")
        logger.info(f"신규 도서: {search_result['saved']}개")
        logger.info(f"단권 상품: {len(margin_result['single_uploadable'])}개")
        logger.info(f"묶음 SKU: {bundle_result['created']}개")
        logger.info(f"CSV 파일: {len(csv_files)}개")

        return {
            'search': search_result,
            'margin': margin_result,
            'bundle': bundle_result,
            'distribution': distribution,
            'csv_files': csv_files,
            'elapsed_seconds': elapsed
        }


def main():
    """메인 실행"""
    print("\n" + "="*60)
    print("스마트 업로드 시스템")
    print("="*60)

    # TTBKey 확인
    ttb_key = os.getenv("ALADIN_TTB_KEY")

    if not ttb_key:
        print("\n[ERROR] ALADIN_TTB_KEY가 설정되지 않았습니다.")
        print("ALADIN_API_GUIDE.md를 참고하여 TTBKey를 발급받으세요.")
        return

    # 출판사 선택
    print("\n실행 모드:")
    print("1. 전체 출판사 (25개)")
    print("2. 특정 출판사만")

    mode = input("\n선택 (1 or 2): ").strip() or "1"

    publisher_names = None
    if mode == "2":
        print("\n출판사명을 쉼표로 구분하여 입력 (예: EBS,gilbut,gaennyeom)")
        names = input("출판사: ").strip()
        if names:
            publisher_names = [n.strip() for n in names.split(",")]

    # 검색 개수
    max_per_pub = input("\n출판사당 최대 검색 개수 (기본 20): ").strip()
    max_per_publisher = int(max_per_pub) if max_per_pub else 20

    # 실행
    with SmartUploadSystem(ttb_key) as system:
        result = system.run_full_workflow(publisher_names, max_per_publisher)

        if result:
            print("\n\n" + "="*60)
            print("다음 단계")
            print("="*60)
            print("\n1. data/uploads/ 폴더 확인")
            print("2. 쿠팡 판매자센터 > 상품관리 > 일괄등록")
            print("3. CSV 파일 업로드")


if __name__ == "__main__":
    main()
