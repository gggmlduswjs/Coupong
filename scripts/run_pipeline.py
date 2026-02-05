"""
실제 운영 파이프라인
===================
알라딘 API → DB 저장 → 마진 분석 → CSV 생성

사용법:
    python scripts/run_pipeline.py                    # 전체 24개 출판사 검색
    python scripts/run_pipeline.py --publishers 개념원리 길벗   # 특정 출판사만
    python scripts/run_pipeline.py --max-results 10   # 출판사당 최대 10개
    python scripts/run_pipeline.py --dry-run           # DB 저장 없이 미리보기
"""
import sys
import os
import argparse
import time
import logging
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 설정
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal, init_db, engine, Base
from app.models.publisher import Publisher
from app.models.book import Book
from app.models.product import Product
from app.models.bundle_sku import BundleSKU
from app.models.account import Account
from app.models.listing import Listing
from config.publishers import PUBLISHERS
from crawlers.aladin_api_crawler import AladinAPICrawler
from uploaders.coupang_csv_generator import CoupangCSVGenerator
from auto_logger import task_context
from obsidian_logger import ObsidianLogger

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 1단계: DB 초기화 및 시딩
# ─────────────────────────────────────────────

def seed_publishers(db):
    """출판사 24개를 publishers 테이블에 시딩"""
    created = 0
    skipped = 0

    for pub_data in PUBLISHERS:
        existing = db.query(Publisher).filter(
            Publisher.name == pub_data["name"]
        ).first()

        if existing:
            skipped += 1
            continue

        margin_rate = pub_data["margin"]
        supply_rate = (100 - margin_rate) / 100.0

        publisher = Publisher(
            name=pub_data["name"],
            margin_rate=margin_rate,
            min_free_shipping=pub_data["min_free_shipping"],
            supply_rate=supply_rate,
            is_active=True
        )
        db.add(publisher)
        created += 1

    db.commit()
    logger.info(f"출판사 시딩 완료: 생성 {created}개, 기존 {skipped}개")
    return created


def seed_accounts(db):
    """5개 쿠팡 계정을 accounts 테이블에 등록"""
    created = 0

    for i in range(1, 6):
        account_id = os.getenv(f"COUPANG_ID_{i}")
        account_pw = os.getenv(f"COUPANG_PW_{i}")

        if not account_id:
            continue

        existing = db.query(Account).filter(
            Account.account_name == account_id
        ).first()

        if existing:
            continue

        account = Account(
            account_name=account_id,
            email=account_id,
            password_encrypted=account_pw or "",
        )
        db.add(account)
        created += 1

    db.commit()
    logger.info(f"계정 등록 완료: {created}개 새로 등록")
    return created


# ─────────────────────────────────────────────
# 2단계: 알라딘 API 검색 → Book 저장
# ─────────────────────────────────────────────

def search_and_save_books(db, crawler, publisher_names=None, max_results=20):
    """
    출판사별 알라딘 API 검색 → books 테이블 저장

    Returns:
        새로 저장된 Book 리스트
    """
    publishers = db.query(Publisher).filter(Publisher.is_active == True).all()
    pub_map = {p.name: p for p in publishers}

    if publisher_names:
        target_names = publisher_names
    else:
        target_names = [p.name for p in publishers]

    all_new_books = []
    total_searched = 0
    total_saved = 0
    total_skipped = 0

    for pub_name in target_names:
        publisher = pub_map.get(pub_name)
        if not publisher:
            logger.warning(f"DB에 없는 출판사: {pub_name}")
            continue

        logger.info(f"\n{'='*50}")
        logger.info(f"검색 중: {pub_name} (매입률 {publisher.margin_rate}%)")
        logger.info(f"{'='*50}")

        # 알라딘 API 검색
        results = crawler.search_by_keyword(pub_name, max_results=max_results)
        total_searched += len(results)

        for item in results:
            # 출판사 매칭 확인
            if not _match_publisher(item.get("publisher", ""), pub_name):
                continue

            isbn = item.get("isbn", "")
            if not isbn:
                continue

            # 중복 체크
            existing = db.query(Book).filter(Book.isbn == isbn).first()
            if existing:
                total_skipped += 1
                continue

            # Book 생성
            book = Book(
                isbn=isbn,
                title=item["title"],
                author=item.get("author", ""),
                publisher_id=publisher.id,
                publisher_name=pub_name,
                list_price=item["original_price"],
                category=item.get("category", "도서"),
                subcategory=item.get("subcategory", ""),
                year=item.get("year"),
                normalized_title=item.get("normalized_title", ""),
                normalized_series=item.get("normalized_series", ""),
                image_url=item.get("image_url", ""),
                description=item.get("description", ""),
                source_url=item.get("kyobo_url", ""),
                publish_date=item.get("publish_date"),
                page_count=item.get("page_count", 0),
                is_processed=False,
                crawled_at=datetime.utcnow()
            )
            book.process_metadata()

            db.add(book)
            all_new_books.append(book)
            total_saved += 1

        db.commit()

        # API 부하 방지
        time.sleep(1)

    logger.info(f"\n도서 검색 완료: 검색 {total_searched}개, 저장 {total_saved}개, 중복 {total_skipped}개")
    return all_new_books


def _match_publisher(api_publisher, target_name):
    """출판사명 매칭 (부분 일치 허용)"""
    api_publisher = api_publisher.strip()
    target_name = target_name.strip()

    if target_name in api_publisher or api_publisher in target_name:
        return True

    # EBS 특수 케이스
    if target_name == "EBS" and "한국교육방송" in api_publisher:
        return True
    if target_name == "한국교육방송공사" and "EBS" in api_publisher:
        return True

    return False


# ─────────────────────────────────────────────
# 3단계: 마진 분석 → Product 생성
# ─────────────────────────────────────────────

def analyze_and_create_products(db, books=None):
    """
    미처리 Book들에 대해 마진 분석 → Product 생성

    Args:
        books: 처리할 Book 리스트 (None이면 is_processed=False인 것 모두)

    Returns:
        (생성된 Product 리스트, 묶음 필요 Book 리스트)
    """
    if books is None:
        books = db.query(Book).filter(Book.is_processed == False).all()

    if not books:
        logger.info("분석할 도서가 없습니다.")
        return [], []

    new_products = []
    bundle_needed = []

    for book in books:
        # 출판사 조회
        publisher = book.publisher
        if not publisher:
            publisher = db.query(Publisher).filter(
                Publisher.id == book.publisher_id
            ).first()

        if not publisher:
            logger.warning(f"출판사 정보 없음: {book.title[:40]}")
            continue

        # 이미 Product가 있는지 확인
        existing = db.query(Product).filter(Product.isbn == book.isbn).first()
        if existing:
            book.is_processed = True
            continue

        # Product 생성
        product = Product.create_from_book(book, publisher)
        db.add(product)
        new_products.append(product)

        # 묶음 필요 도서 추적
        if not product.can_upload_single:
            bundle_needed.append(book)

        # 처리 완료 표시
        book.is_processed = True

        margin_info = publisher.calculate_margin(book.list_price)
        policy_str = product.shipping_policy
        logger.info(
            f"  {book.title[:35]:35s} | {book.list_price:>7,}원 | "
            f"순마진 {margin_info['net_margin']:>6,}원 | {policy_str}"
        )

    db.commit()

    free_count = sum(1 for p in new_products if p.shipping_policy == 'free')
    paid_count = sum(1 for p in new_products if p.shipping_policy == 'paid')
    bundle_count = sum(1 for p in new_products if p.shipping_policy == 'bundle_required')

    logger.info(f"\n마진 분석 완료: 총 {len(new_products)}개")
    logger.info(f"  무료배송: {free_count}개 | 유료배송: {paid_count}개 | 묶음필요: {bundle_count}개")

    return new_products, bundle_needed


# ─────────────────────────────────────────────
# 4단계: 묶음 SKU 생성
# ─────────────────────────────────────────────

def create_bundle_skus(db, bundle_needed_books=None):
    """저마진 도서를 묶어서 BundleSKU 생성"""
    if not bundle_needed_books:
        # 묶음 필요 상품 조회
        bundle_products = db.query(Product).filter(
            Product.shipping_policy == 'bundle_required'
        ).all()

        if not bundle_products:
            logger.info("묶음 생성할 도서가 없습니다.")
            return []

        # ISBN으로 Book 조회
        isbns = [p.isbn for p in bundle_products]
        bundle_needed_books = db.query(Book).filter(Book.isbn.in_(isbns)).all()

    if not bundle_needed_books:
        return []

    # 출판사 + 시리즈 + 연도로 그룹핑
    groups = {}
    for book in bundle_needed_books:
        key = (book.publisher_id, book.normalized_series or "", book.year or 0)
        if key not in groups:
            groups[key] = []
        groups[key].append(book)

    new_bundles = []

    for (pub_id, series, year), books in groups.items():
        if len(books) < 2:
            continue

        publisher = db.query(Publisher).get(pub_id)
        if not publisher:
            continue

        # 기존 묶음 체크
        bundle_key = f"{pub_id}_{series}_{year}"
        existing = db.query(BundleSKU).filter(
            BundleSKU.bundle_key == bundle_key
        ).first()

        if existing:
            continue

        # 2~5권 묶음 생성
        bundle_books = books[:5]

        try:
            bundle = BundleSKU.create_bundle(
                books=bundle_books,
                publisher=publisher,
                year=year or datetime.now().year,
                normalized_series=series or "기타"
            )
            db.add(bundle)
            new_bundles.append(bundle)
            logger.info(f"  묶음 생성: {bundle.bundle_name} ({bundle.net_margin:,}원)")
        except Exception as e:
            logger.error(f"  묶음 생성 실패: {e}")

    db.commit()
    logger.info(f"묶음 SKU 생성 완료: {len(new_bundles)}개")
    return new_bundles


# ─────────────────────────────────────────────
# 5단계: 계정별 CSV 생성
# ─────────────────────────────────────────────

def generate_account_csvs(db):
    """
    업로드 가능한 상품 → 5개 계정별 CSV 생성
    중복 방지: listings 테이블 기반
    """
    # 활성 계정 조회
    accounts = db.query(Account).filter(Account.is_active == True).all()
    if not accounts:
        logger.warning("등록된 계정이 없습니다.")
        return {}

    # 업로드 가능한 단권 상품 (ready 상태)
    products = db.query(Product).filter(
        Product.status == 'ready',
        Product.can_upload_single == True
    ).all()

    # 업로드 가능한 묶음 상품
    bundles = db.query(BundleSKU).filter(
        BundleSKU.status == 'ready'
    ).all()

    if not products and not bundles:
        logger.info("업로드할 상품이 없습니다.")
        return {}

    generator = CoupangCSVGenerator()
    result = {}

    for account in accounts:
        # 이 계정에 아직 등록되지 않은 상품 필터링
        account_products = []

        for product in products:
            # Listing 중복 체크
            existing_listing = db.query(Listing).filter(
                Listing.account_id == account.id,
                Listing.isbn == product.isbn
            ).first()

            if existing_listing:
                continue

            book = db.query(Book).filter(Book.isbn == product.isbn).first()
            if not book:
                continue

            account_products.append({
                "product_name": book.title,
                "original_price": book.list_price,
                "sale_price": product.sale_price,
                "isbn": book.isbn,
                "publisher": book.publisher_name or "",
                "author": book.author or "",
                "main_image_url": book.image_url or "",
                "description": book.description or "상세페이지 참조",
                "shipping_policy": product.shipping_policy,
                "net_margin": product.net_margin,
            })

        if not account_products:
            logger.info(f"  {account.account_name}: 새로 업로드할 상품 없음")
            continue

        # CSV 생성
        filepath = generator.generate_csv(account_products, account.account_name)
        result[account.account_name] = {
            "filepath": filepath,
            "count": len(account_products),
        }

        # Listing 기록 (CSV 생성 = 업로드 준비 완료)
        for prod_data in account_products:
            product_obj = db.query(Product).filter(
                Product.isbn == prod_data["isbn"]
            ).first()

            if product_obj:
                listing = Listing.create_from_product(
                    account_id=account.id,
                    product=product_obj,
                    upload_method='csv'
                )
                db.add(listing)

        db.commit()
        logger.info(f"  {account.account_name}: {len(account_products)}개 상품 CSV 생성")

    return result


# ─────────────────────────────────────────────
# 메인 파이프라인
# ─────────────────────────────────────────────

def run_pipeline(publisher_names=None, max_results=20, dry_run=False):
    """전체 파이프라인 실행"""

    obs = ObsidianLogger()

    start_time = time.time()
    print("\n" + "=" * 60)
    print("  쿠팡 도서 자동화 파이프라인")
    print(f"  시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # API 키 확인
    ttb_key = os.getenv("ALADIN_TTB_KEY")
    if not ttb_key:
        print("\n[ERROR] ALADIN_TTB_KEY가 .env에 설정되지 않았습니다.")
        return

    with task_context("파이프라인 실행", f"출판사당 최대 {max_results}개 검색, dry_run={dry_run}"):

        # DB 초기화
        print("\n[1/5] DB 초기화...")
        init_db()

        db = SessionLocal()

        try:
            # 시딩
            print("\n[2/5] 출판사 & 계정 등록...")
            with task_context("출판사/계정 시딩", "24개 출판사 + 5개 쿠팡 계정 등록"):
                seed_publishers(db)
                seed_accounts(db)

            # 알라딘 검색
            print(f"\n[3/5] 알라딘 API 도서 검색 (출판사당 최대 {max_results}개)...")
            with task_context("알라딘 API 검색", f"출판사당 최대 {max_results}개 도서 검색"):
                crawler = AladinAPICrawler(ttb_key=ttb_key)
                new_books = search_and_save_books(
                    db, crawler,
                    publisher_names=publisher_names,
                    max_results=max_results
                )

            if dry_run:
                print("\n[DRY-RUN] DB 저장/CSV 생성 건너뜀")
                db.rollback()
                return

            # 마진 분석
            print("\n[4/5] 마진 분석 & 상품 생성...")
            with task_context("마진 분석", "도서별 마진 계산 및 배송 정책 결정"):
                new_products, bundle_needed = analyze_and_create_products(db)

            # 묶음 생성
            if bundle_needed:
                print(f"\n  묶음 SKU 생성 ({len(bundle_needed)}개 저마진 도서)...")
                with task_context("묶음 SKU 생성", f"{len(bundle_needed)}개 저마진 도서 묶음 처리"):
                    create_bundle_skus(db, bundle_needed)

            # CSV 생성
            print("\n[5/5] 계정별 CSV 생성...")
            with task_context("CSV 생성", "5개 계정별 쿠팡 업로드용 CSV 생성"):
                csv_result = generate_account_csvs(db)

            # 결과 요약
            elapsed = time.time() - start_time

            total_books = db.query(Book).count()
            total_products = db.query(Product).count()
            total_bundles = db.query(BundleSKU).count()
            total_listings = db.query(Listing).count()

            # Obsidian에 결과 기록
            csv_summary = ""
            if csv_result:
                csv_lines = []
                for acc_name, info in csv_result.items():
                    csv_lines.append(f"- **{acc_name}**: {info['count']}개 상품")
                csv_summary = "\n".join(csv_lines)
            else:
                csv_summary = "- 새로 생성된 CSV 없음 (모든 상품이 이미 등록됨)"

            obs.log_to_daily(f"""**파이프라인 실행 결과**

| 항목 | 수량 |
|------|------|
| 도서 | {total_books}개 |
| 단권상품 | {total_products}개 |
| 묶음상품 | {total_bundles}개 |
| 등록현황 | {total_listings}개 |

**생성된 CSV:**
{csv_summary}

**소요 시간:** {elapsed:.1f}초""", "파이프라인 결과")

            print("\n" + "=" * 60)
            print("  파이프라인 완료")
            print("=" * 60)

            print(f"\n  DB 현황:")
            print(f"    도서:     {total_books}개")
            print(f"    단권상품: {total_products}개")
            print(f"    묶음상품: {total_bundles}개")
            print(f"    등록현황: {total_listings}개")

            if csv_result:
                print(f"\n  생성된 CSV:")
                for acc_name, info in csv_result.items():
                    print(f"    {acc_name}: {info['count']}개 상품 → {info['filepath']}")
            else:
                print("\n  새로 생성된 CSV 없음 (모든 상품이 이미 등록됨)")

            print(f"\n  소요 시간: {elapsed:.1f}초")
            print(f"  완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 60)

        except Exception as e:
            logger.error(f"파이프라인 오류: {e}", exc_info=True)
            obs.log_to_daily(f"**파이프라인 오류:** `{type(e).__name__}: {e}`", "파이프라인 실패")
            db.rollback()
            raise
        finally:
            db.close()


def main():
    parser = argparse.ArgumentParser(description="쿠팡 도서 자동화 파이프라인")
    parser.add_argument(
        "--publishers", nargs="+",
        help="특정 출판사만 검색 (예: --publishers 개념원리 길벗)"
    )
    parser.add_argument(
        "--max-results", type=int, default=20,
        help="출판사당 최대 검색 수 (기본: 20)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="DB 저장 없이 미리보기만"
    )

    args = parser.parse_args()

    run_pipeline(
        publisher_names=args.publishers,
        max_results=args.max_results,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
