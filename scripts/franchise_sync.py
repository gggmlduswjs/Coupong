"""
프랜차이즈 동기화 엔진
=======================
알라딘 신간 수집 → 마진 분석 → 갭 분석 → 5개 계정 일괄 등록

사용법:
    from scripts.franchise_sync import FranchiseSync
    sync = FranchiseSync()
    report = sync.sync_all(dry_run=True)
"""
import sys
import os
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

# 프로젝트 루트 설정
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import inspect, text
from app.database import SessionLocal, init_db, engine
from app.models.publisher import Publisher
from app.models.book import Book
from app.models.product import Product
from app.models.account import Account
from app.models.listing import Listing
from app.constants import WING_ACCOUNT_ENV_MAP, CRAWL_MIN_PRICE, CRAWL_EXCLUDE_KEYWORDS
from crawlers.aladin_api_crawler import AladinAPICrawler
from app.api.coupang_wing_client import CoupangWingClient
from uploaders.coupang_api_uploader import CoupangAPIUploader
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class FranchiseSync:
    """프랜차이즈 동기화: 신간 수집 + 갭 메우기"""

    def __init__(self, db=None):
        self.db = db or SessionLocal()
        self._owns_db = db is None
        self.ttb_key = os.getenv("ALADIN_TTB_KEY", "")

    def close(self):
        if self._owns_db:
            self.db.close()

    # ─────────────────────────────────────────────
    # Step 1: 알라딘 신간 크롤링 + DB 저장
    # ─────────────────────────────────────────────

    def crawl_new_releases(
        self,
        max_results: int = 200,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        알라딘 신간 API로 거래 출판사의 신간 수집 → DB 저장

        Args:
            max_results: 알라딘 API에서 가져올 최대 항목 수
            progress_callback: 진행률 콜백 fn(current, total, message)

        Returns:
            {"searched": int, "new": int, "skipped": int, "books": [Book]}
        """
        if not self.ttb_key:
            logger.error("ALADIN_TTB_KEY가 설정되지 않았습니다.")
            return {"searched": 0, "new": 0, "skipped": 0, "books": []}

        # DB에서 활성 출판사 이름 가져오기
        publishers = self.db.query(Publisher).filter(Publisher.is_active == True).all()
        pub_names = [p.name for p in publishers]
        pub_map = {p.name: p for p in publishers}

        if not pub_names:
            logger.warning("활성 출판사가 없습니다.")
            return {"searched": 0, "new": 0, "skipped": 0, "books": []}

        crawler = AladinAPICrawler(ttb_key=self.ttb_key)

        if progress_callback:
            progress_callback(0, 1, "알라딘 신간 API 조회 중...")

        # 신간 리스트 API 호출 (출판사 필터링 포함)
        results = crawler.fetch_new_releases(
            max_results=max_results,
            publisher_names=pub_names,
        )

        new_books = []
        skipped = 0
        seen_isbns = set()  # 배치 내 중복 방지

        # ISBN 프리로드: DB 전체 ISBN + sales_point를 메모리에 로드
        existing_isbn_sp = {
            isbn: sp for isbn, sp in
            self.db.query(Book.isbn, Book.sales_point).all()
        }
        sp_updates = {}  # {isbn: new_sales_point} 배치 업데이트용

        total = len(results)
        for i, item in enumerate(results):
            isbn = item.get("isbn", "")
            if not isbn:
                skipped += 1
                continue

            # 배치 내 중복 체크
            if isbn in seen_isbns:
                skipped += 1
                continue
            seen_isbns.add(isbn)

            # DB 중복 체크 (프리로드된 딕셔너리에서 O(1) 조회)
            if isbn in existing_isbn_sp:
                # 기존 책의 salesPoint 갱신 (배치로 모아서 처리)
                new_sp = item.get("sales_point", 0) or 0
                if new_sp and new_sp != (existing_isbn_sp[isbn] or 0):
                    sp_updates[isbn] = new_sp
                skipped += 1
                continue

            # 출판사 매칭
            api_pub = item.get("publisher", "")
            matched_pub = None
            for pn, pub_obj in pub_map.items():
                if AladinAPICrawler._match_publisher_name(api_pub, pn):
                    matched_pub = pub_obj
                    break

            if not matched_pub:
                skipped += 1
                continue

            book = Book(
                isbn=isbn,
                title=item["title"],
                author=item.get("author", ""),
                publisher_id=matched_pub.id,
                list_price=item["original_price"],
                year=item.get("year"),
                normalized_title=item.get("normalized_title", ""),
                normalized_series=item.get("normalized_series", ""),
                sales_point=item.get("sales_point", 0),
                crawled_at=datetime.utcnow(),
            )
            book.process_metadata()

            self.db.add(book)
            new_books.append(book)

            if progress_callback and total > 0:
                progress_callback(i + 1, total, f"저장 중: {item['title'][:30]}...")

        # 기존 책 sales_point 배치 업데이트
        if sp_updates:
            for book in self.db.query(Book).filter(Book.isbn.in_(list(sp_updates.keys()))):
                book.sales_point = sp_updates[book.isbn]
            logger.info(f"기존 도서 salesPoint 갱신: {len(sp_updates)}개")

        self.db.commit()

        result = {
            "searched": total,
            "new": len(new_books),
            "skipped": skipped,
            "books": new_books,
        }
        logger.info(f"신간 크롤링 완료: 검색 {total}개, 신규 {len(new_books)}개, 스킵 {skipped}개")
        return result

    # ─────────────────────────────────────────────
    # Step 1-B: 출판사별 키워드 검색 크롤링
    # ─────────────────────────────────────────────

    def crawl_by_publisher(
        self,
        max_per_publisher: int = 20,
        publisher_names: List[str] = None,
        progress_callback=None,
        year_filter: int = None,
    ) -> Dict[str, Any]:
        """
        출판사 이름으로 알라딘 키워드 검색 → DB 저장

        기존 run_pipeline.py의 search_and_save_books()와 동일한 방식.
        출판사마다 개별 검색하므로 정확도가 높음.

        Args:
            max_per_publisher: 출판사당 최대 검색 수
            publisher_names: 특정 출판사만 (None이면 전체 활성 출판사)
            progress_callback: fn(current, total, message)
            year_filter: 출간 연도 필터 (예: 2025 → 2025년 이후만)

        Returns:
            {"searched": int, "new": int, "skipped": int, "books": [Book]}
        """
        if not self.ttb_key:
            logger.error("ALADIN_TTB_KEY가 설정되지 않았습니다.")
            return {"searched": 0, "new": 0, "skipped": 0, "books": []}

        publishers = self.db.query(Publisher).filter(Publisher.is_active == True).all()
        pub_map = {p.name: p for p in publishers}

        if publisher_names:
            target_names = [n for n in publisher_names if n in pub_map]
        else:
            target_names = list(pub_map.keys())

        if not target_names:
            return {"searched": 0, "new": 0, "skipped": 0, "books": []}

        crawler = AladinAPICrawler(ttb_key=self.ttb_key)

        all_new_books = []
        total_searched = 0
        total_skipped = 0
        seen_isbns = set()

        # ISBN 프리로드: DB 전체 ISBN + sales_point를 메모리에 로드
        existing_isbn_sp = {
            isbn: sp for isbn, sp in
            self.db.query(Book.isbn, Book.sales_point).all()
        }
        sp_updates = {}  # {isbn: new_sales_point} 배치 업데이트용

        for idx, pub_name in enumerate(target_names):
            publisher = pub_map[pub_name]

            if progress_callback:
                progress_callback(idx, len(target_names), f"{pub_name} 검색 중...")

            # 원래 이름 + 별칭으로 검색 (씨톡→씨앤톡 등)
            search_names = AladinAPICrawler.get_search_names(pub_name)
            results = []
            seen_isbn_batch = set()  # 정렬 간 중복 제거용
            for sname in search_names:
                # 최신순 크롤링
                batch = crawler.search_by_keyword(
                    sname, max_results=max_per_publisher,
                    sort="PublishTime", year_filter=year_filter,
                )
                for b in batch:
                    if b.get("isbn") and b["isbn"] not in seen_isbn_batch:
                        seen_isbn_batch.add(b["isbn"])
                        results.append(b)
                time.sleep(0.5)

                # 판매량순 크롤링 (잘 팔리는 책 우선 수집)
                batch_sp = crawler.search_by_keyword(
                    sname, max_results=max_per_publisher,
                    sort="SalesPoint", year_filter=year_filter,
                )
                for b in batch_sp:
                    if b.get("isbn") and b["isbn"] not in seen_isbn_batch:
                        seen_isbn_batch.add(b["isbn"])
                        results.append(b)
                time.sleep(0.5)
            total_searched += len(results)

            for item in results:
                # 출판사 매칭
                if not AladinAPICrawler._match_publisher_name(item.get("publisher", ""), pub_name):
                    continue

                # 정가 최소 기준 필터
                item_price = item.get("original_price", 0) or 0
                if item_price < CRAWL_MIN_PRICE:
                    total_skipped += 1
                    continue

                # 제외 키워드 필터 (제목 + 카테고리)
                item_title = item.get("title", "")
                item_category = item.get("category", "")
                _check_text = item_title + " " + item_category
                if any(kw in _check_text for kw in CRAWL_EXCLUDE_KEYWORDS):
                    total_skipped += 1
                    continue

                isbn = item.get("isbn", "")
                if not isbn:
                    total_skipped += 1
                    continue

                # 배치 내 중복
                if isbn in seen_isbns:
                    total_skipped += 1
                    continue
                seen_isbns.add(isbn)

                # DB 중복 (프리로드된 딕셔너리에서 O(1) 조회)
                if isbn in existing_isbn_sp:
                    # 기존 책의 salesPoint 갱신 (배치로 모아서 처리)
                    new_sp = item.get("sales_point", 0) or 0
                    if new_sp and new_sp != (existing_isbn_sp[isbn] or 0):
                        sp_updates[isbn] = new_sp
                        existing_isbn_sp[isbn] = new_sp  # 딕셔너리도 갱신
                    total_skipped += 1
                    continue

                book = Book(
                    isbn=isbn,
                    title=item["title"],
                    author=item.get("author", ""),
                    publisher_id=publisher.id,
                    list_price=item["original_price"],
                    year=item.get("year"),
                    normalized_title=item.get("normalized_title", ""),
                    normalized_series=item.get("normalized_series", ""),
                    sales_point=item.get("sales_point", 0),
                    crawled_at=datetime.utcnow(),
                )
                book.process_metadata()
                self.db.add(book)
                all_new_books.append(book)
                existing_isbn_sp[isbn] = item.get("sales_point", 0)  # 프리로드 딕셔너리에 추가

            # 기존 책 sales_point 배치 업데이트
            if sp_updates:
                for book in self.db.query(Book).filter(Book.isbn.in_(list(sp_updates.keys()))):
                    if book.isbn in sp_updates:
                        book.sales_point = sp_updates[book.isbn]
                logger.info(f"기존 도서 salesPoint 갱신: {len(sp_updates)}개")
                sp_updates.clear()

            self.db.commit()
            time.sleep(1)  # API 부하 방지

        if progress_callback:
            progress_callback(len(target_names), len(target_names), "완료!")

        result = {
            "searched": total_searched,
            "new": len(all_new_books),
            "skipped": total_skipped,
            "books": all_new_books,
        }
        logger.info(f"출판사별 크롤링 완료: 검색 {total_searched}개, 신규 {len(all_new_books)}개, 스킵 {total_skipped}개")
        return result

    # ─────────────────────────────────────────────
    # Step 2: 마진 분석 + Product 생성
    # ─────────────────────────────────────────────

    def analyze_products(self, books: List[Book] = None) -> Dict[str, Any]:
        """
        미처리 Book → 마진 분석 → Product 생성

        Returns:
            {"created": int, "bundle_needed": int, "products": [Product]}
        """
        if books is None:
            # Product가 아직 없는 Book = 미처리
            from sqlalchemy import exists
            books = self.db.query(Book).filter(
                ~exists().where(Product.book_id == Book.id)
            ).all()

        if not books:
            logger.info("분석할 신규 도서가 없습니다.")
            return {"created": 0, "bundle_needed": 0, "products": []}

        new_products = []
        bundle_count = 0

        for book in books:
            publisher = book.publisher
            if not publisher:
                publisher = self.db.query(Publisher).filter(
                    Publisher.id == book.publisher_id
                ).first()

            if not publisher:
                continue

            # 이미 Product 존재하면 스킵
            existing = self.db.query(Product).filter(Product.isbn == book.isbn).first()
            if existing:
                continue

            product = Product.create_from_book(book, publisher)
            self.db.add(product)
            new_products.append(product)

            if not product.can_upload_single:
                bundle_count += 1

            # Product 생성 완료 (is_processed 불필요 — Product 존재로 판별)

        self.db.commit()

        result = {
            "created": len(new_products),
            "bundle_needed": bundle_count,
            "products": new_products,
        }
        logger.info(f"마진 분석 완료: {len(new_products)}개 Product 생성, 묶음필요 {bundle_count}개")
        return result

    # ─────────────────────────────────────────────
    # Step 3: 갭 분석 (계정별 미등록 도서)
    # ─────────────────────────────────────────────

    def find_gaps(self) -> Dict[str, Dict[str, Any]]:
        """
        계정별 미등록 도서(갭) 분석

        Returns:
            {
                "007-book": {"registered": 400, "missing": 81, "total": 481,
                             "coverage": 83.2, "products": [Product, ...]},
                ...
            }
        """
        # 업로드 가능한 전체 상품
        all_products = self.db.query(Product).filter(
            Product.status == 'ready',
            Product.can_upload_single == True,
        ).all()
        total_products = len(all_products)

        if total_products == 0:
            logger.info("업로드 가능한 상품이 없습니다.")
            return {}

        product_isbns = {p.isbn: p for p in all_products}

        # 활성 WING API 계정
        accounts = self.db.query(Account).filter(
            Account.is_active == True,
            Account.wing_api_enabled == True,
        ).all()

        gaps = {}

        for account in accounts:
            # 이미 등록된 ISBN (coupang_product_id가 있는 것만)
            registered_isbns = set()
            listings = self.db.query(Listing.isbn).filter(
                Listing.account_id == account.id,
                Listing.isbn.isnot(None),
            ).all()
            for (isbn,) in listings:
                if isbn:
                    registered_isbns.add(isbn)

            # 갭 = 전체 - 이미등록
            missing_products = [
                p for isbn, p in product_isbns.items()
                if isbn not in registered_isbns
            ]

            registered_count = len(registered_isbns & set(product_isbns.keys()))
            missing_count = len(missing_products)
            coverage = (registered_count / total_products * 100) if total_products > 0 else 0

            gaps[account.account_name] = {
                "account": account,
                "registered": registered_count,
                "missing": missing_count,
                "total": total_products,
                "coverage": round(coverage, 1),
                "products": missing_products,
            }

            logger.info(
                f"  {account.account_name}: "
                f"등록 {registered_count} / 미등록 {missing_count} / "
                f"전체 {total_products} ({coverage:.1f}%)"
            )

        return gaps

    # ─────────────────────────────────────────────
    # Step 4: 특정 계정에 미등록 도서 업로드
    # ─────────────────────────────────────────────

    def upload_to_account(
        self,
        account: Account,
        products: List[Product],
        dry_run: bool = False,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        특정 계정에 미등록 상품 업로드

        Args:
            account: Account 인스턴스
            products: 업로드할 Product 리스트
            dry_run: True면 페이로드만 빌드 (실제 등록 안 함)
            progress_callback: fn(current, total, message)

        Returns:
            {"success": int, "failed": int, "results": [dict]}
        """
        if not products:
            return {"success": 0, "failed": 0, "results": []}

        outbound_code = account.outbound_shipping_code or ""
        return_code = account.return_center_code or ""

        if not outbound_code or not return_code:
            logger.error(f"{account.account_name}: 출고지/반품지 코드 미설정")
            return {"success": 0, "failed": len(products), "results": [
                {"isbn": p.isbn, "success": False, "message": "출고지/반품지 코드 미설정"}
                for p in products
            ]}

        # WING 클라이언트 생성
        client = self._create_wing_client(account)
        if not client:
            logger.error(f"{account.account_name}: WING API 클라이언트 생성 실패")
            return {"success": 0, "failed": len(products), "results": [
                {"isbn": p.isbn, "success": False, "message": "API 키 미설정"}
                for p in products
            ]}

        uploader = CoupangAPIUploader(client, vendor_user_id=account.account_name)

        success_count = 0
        fail_count = 0
        results = []
        total = len(products)

        for i, product in enumerate(products):
            book = self.db.query(Book).filter(Book.id == product.book_id).first()
            if not book:
                fail_count += 1
                results.append({"isbn": product.isbn, "success": False, "message": "Book 없음"})
                continue

            publisher = book.publisher
            pd_data = {
                "product_name": book.title,
                "publisher": publisher.name if publisher else "",
                "author": "",
                "isbn": book.isbn,
                "original_price": book.list_price,
                "sale_price": product.sale_price,
                "main_image_url": "",
                "description": "상세페이지 참조",
                "shipping_policy": product.shipping_policy,
            }

            if progress_callback:
                progress_callback(i + 1, total, f"[{account.account_name}] {book.title[:30]}...")

            if dry_run:
                # 페이로드 빌드만
                try:
                    payload = uploader.build_product_payload(pd_data, outbound_code, return_code)
                    results.append({
                        "isbn": product.isbn,
                        "title": book.title[:40],
                        "success": True,
                        "message": "Dry Run OK",
                        "category": payload.get("displayCategoryCode", ""),
                    })
                    success_count += 1
                except Exception as e:
                    results.append({"isbn": product.isbn, "title": book.title[:40],
                                    "success": False, "message": str(e)[:100]})
                    fail_count += 1
            else:
                # 실제 등록
                res = uploader.upload_product(pd_data, outbound_code, return_code)
                if res["success"]:
                    success_count += 1
                    sid = res["seller_product_id"]
                    results.append({
                        "isbn": product.isbn, "title": book.title[:40],
                        "success": True, "message": f"등록 성공 (ID={sid})",
                        "seller_product_id": sid,
                    })
                    # Listing 레코드 생성
                    try:
                        listing = Listing(
                            account_id=account.id,
                            product_id=product.id,
                            coupang_product_id=int(sid) if sid else 0,
                            coupang_status='active',
                            sale_price=product.sale_price,
                            original_price=product.list_price,
                            product_name=book.title,
                            isbn=product.isbn,
                            synced_at=datetime.utcnow(),
                        )
                        self.db.add(listing)
                        self.db.commit()
                    except Exception as db_e:
                        logger.warning(f"Listing 저장 실패: {db_e}")
                        self.db.rollback()
                else:
                    fail_count += 1
                    results.append({
                        "isbn": product.isbn, "title": book.title[:40],
                        "success": False, "message": res["message"][:100],
                    })

        logger.info(f"{account.account_name}: 성공 {success_count}, 실패 {fail_count}")
        return {"success": success_count, "failed": fail_count, "results": results}

    # ─────────────────────────────────────────────
    # 전체 동기화
    # ─────────────────────────────────────────────

    def sync_all(
        self,
        dry_run: bool = False,
        max_crawl: int = 200,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        전체 동기화: 크롤링 → 분석 → 갭 분석 → 계정별 업로드

        Args:
            dry_run: True면 실제 등록 안 함
            max_crawl: 신간 크롤링 최대 수
            progress_callback: fn(current, total, message)

        Returns:
            전체 결과 리포트
        """
        report = {
            "started_at": datetime.now().isoformat(),
            "dry_run": dry_run,
            "crawl": None,
            "analyze": None,
            "gaps": {},
            "uploads": {},
        }

        # Step 1: 신간 크롤링
        logger.info("=" * 50)
        logger.info("[1/4] 신간 크롤링...")
        crawl_result = self.crawl_new_releases(
            max_results=max_crawl,
            progress_callback=progress_callback,
        )
        report["crawl"] = {
            "searched": crawl_result["searched"],
            "new": crawl_result["new"],
            "skipped": crawl_result["skipped"],
        }

        # Step 2: 마진 분석
        logger.info("[2/4] 마진 분석...")
        analyze_result = self.analyze_products(crawl_result["books"])
        report["analyze"] = {
            "created": analyze_result["created"],
            "bundle_needed": analyze_result["bundle_needed"],
        }

        # Step 3: 갭 분석
        logger.info("[3/4] 갭 분석...")
        gaps = self.find_gaps()
        for acc_name, gap_info in gaps.items():
            report["gaps"][acc_name] = {
                "registered": gap_info["registered"],
                "missing": gap_info["missing"],
                "total": gap_info["total"],
                "coverage": gap_info["coverage"],
            }

        # Step 4: 계정별 업로드
        logger.info("[4/4] 계정별 업로드...")
        for acc_name, gap_info in gaps.items():
            if not gap_info["products"]:
                report["uploads"][acc_name] = {"success": 0, "failed": 0, "skipped": True}
                continue

            upload_result = self.upload_to_account(
                account=gap_info["account"],
                products=gap_info["products"],
                dry_run=dry_run,
                progress_callback=progress_callback,
            )
            report["uploads"][acc_name] = {
                "success": upload_result["success"],
                "failed": upload_result["failed"],
                "results": upload_result["results"],
            }

        report["finished_at"] = datetime.now().isoformat()
        logger.info("=" * 50)
        logger.info("프랜차이즈 동기화 완료!")
        return report

    # ─────────────────────────────────────────────
    # 유틸리티
    # ─────────────────────────────────────────────

    def _create_wing_client(self, account: Account) -> Optional[CoupangWingClient]:
        """Account로부터 WING API 클라이언트 생성"""
        vendor_id = account.vendor_id or ""
        access_key = account.wing_access_key or ""
        secret_key = account.wing_secret_key or ""

        # DB에 없으면 환경변수에서 시도
        if not access_key:
            env_prefix = WING_ACCOUNT_ENV_MAP.get(account.account_name, "")
            if env_prefix:
                vendor_id = os.getenv(f"{env_prefix}_VENDOR_ID", vendor_id)
                access_key = os.getenv(f"{env_prefix}_ACCESS_KEY", "")
                secret_key = os.getenv(f"{env_prefix}_SECRET_KEY", "")

        if not all([vendor_id, access_key, secret_key]):
            return None

        return CoupangWingClient(vendor_id, access_key, secret_key)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="프랜차이즈 동기화")
    parser.add_argument("--dry-run", action="store_true", help="실제 등록 없이 테스트")
    parser.add_argument("--max-crawl", type=int, default=200, help="신간 크롤링 최대 수")
    parser.add_argument("--gaps-only", action="store_true", help="갭 분석만 실행")
    args = parser.parse_args()

    init_db()
    sync = FranchiseSync()

    try:
        if args.gaps_only:
            gaps = sync.find_gaps()
            print(f"\n{'계정':<12} {'등록':>6} {'미등록':>6} {'전체':>6} {'커버리지':>8}")
            print("-" * 42)
            for name, info in gaps.items():
                print(f"{name:<12} {info['registered']:>6} {info['missing']:>6} "
                      f"{info['total']:>6} {info['coverage']:>7.1f}%")
        else:
            report = sync.sync_all(dry_run=args.dry_run, max_crawl=args.max_crawl)
            print(f"\n크롤링: 검색 {report['crawl']['searched']}개, 신규 {report['crawl']['new']}개")
            print(f"분석: {report['analyze']['created']}개 Product 생성")
            for name, info in report["uploads"].items():
                if info.get("skipped"):
                    print(f"  {name}: 미등록 도서 없음")
                else:
                    print(f"  {name}: 성공 {info['success']}, 실패 {info['failed']}")
    finally:
        sync.close()
