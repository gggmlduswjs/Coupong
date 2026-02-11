"""
실제 운영 파이프라인
===================
알라딘 API → DB 저장 → 마진 분석 → 상품 등록 (API/CSV)

사용법:
    python scripts/run_pipeline.py                              # 전체 24개 출판사 검색
    python scripts/run_pipeline.py --publishers 개념원리 길벗   # 특정 출판사만
    python scripts/run_pipeline.py --max-results 10             # 출판사당 최대 10개
    python scripts/run_pipeline.py --dry-run                    # DB 저장 없이 미리보기
    python scripts/run_pipeline.py --upload-method csv          # CSV만 생성 (기존 방식)
    python scripts/run_pipeline.py --upload-method api          # API만 등록
    python scripts/run_pipeline.py --upload-method auto         # API 우선, CSV 폴백 (기본)
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

from sqlalchemy import inspect, text
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
from app.constants import WING_ACCOUNT_ENV_MAP
from scripts.franchise_sync import FranchiseSync
from auto_logger import task_context
from obsidian_logger import ObsidianLogger

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def _migrate_account_columns():
    """Account 테이블에 WING API 컬럼 추가 (SQLite ALTER TABLE)"""
    try:
        inspector = inspect(engine)
        existing_cols = {col["name"] for col in inspector.get_columns("accounts")}

        new_cols = {
            "vendor_id": "VARCHAR(20)",
            "wing_access_key": "VARCHAR(100)",
            "wing_secret_key": "VARCHAR(100)",
            "wing_api_enabled": "BOOLEAN DEFAULT 0",
            "outbound_shipping_code": "VARCHAR(50)",
            "return_center_code": "VARCHAR(50)",
        }

        with engine.connect() as conn:
            for col_name, col_type in new_cols.items():
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE accounts ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"  컬럼 추가: accounts.{col_name}")
            conn.commit()
    except Exception:
        pass  # 테이블이 아직 없으면 init_db()에서 생성됨


def _migrate_product_registration_status():
    """(삭제됨 — registration_status 컬럼 제거)"""
    pass


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
        supply_rate = margin_rate / 100.0

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
    """5개 쿠팡 계정을 accounts 테이블에 등록 + WING API 크레덴셜 연결"""
    created = 0
    wing_updated = 0

    for i in range(1, 6):
        account_id = os.getenv(f"COUPANG_ID_{i}")
        account_pw = os.getenv(f"COUPANG_PW_{i}")

        if not account_id:
            continue

        existing = db.query(Account).filter(
            Account.account_name == account_id
        ).first()

        if not existing:
            existing = Account(
                account_name=account_id,
                email=account_id,
            )
            db.add(existing)
            created += 1

        # WING API 크레덴셜 연결
        env_prefix = WING_ACCOUNT_ENV_MAP.get(account_id)
        if env_prefix and not existing.has_wing_api:
            vendor_id = os.getenv(f"{env_prefix}_VENDOR_ID")
            access_key = os.getenv(f"{env_prefix}_ACCESS_KEY")
            secret_key = os.getenv(f"{env_prefix}_SECRET_KEY")

            if all([vendor_id, access_key, secret_key]):
                existing.vendor_id = vendor_id
                existing.wing_access_key = access_key
                existing.wing_secret_key = secret_key
                existing.wing_api_enabled = True
                wing_updated += 1

    db.commit()
    logger.info(f"계정 등록 완료: {created}개 새로 등록, WING API {wing_updated}개 연결")
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
                publisher_id=publisher.id,
                list_price=item["original_price"],
                year=item.get("year"),
                normalized_title=item.get("normalized_title", ""),
                normalized_series=item.get("normalized_series", ""),
                sales_point=item.get("sales_point", 0),
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
        books: 처리할 Book 리스트 (None이면 Product 미생성 Book 모두)

    Returns:
        (생성된 Product 리스트, 묶음 필요 Book 리스트)
    """
    if books is None:
        from sqlalchemy import exists
        books = db.query(Book).filter(
            ~exists().where(Product.book_id == Book.id)
        ).all()

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
            continue

        # Product 생성
        product = Product.create_from_book(book, publisher)
        db.add(product)
        new_products.append(product)

        # 묶음 필요 도서 추적
        if not product.can_upload_single:
            bundle_needed.append(book)

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
# 5단계: 계정별 상품 등록 (API 우선 / CSV 폴백)
# ─────────────────────────────────────────────

def upload_products(db, method='auto'):
    """
    업로드 가능한 상품 → 계정별 등록
    - method='auto': WING API 활성 계정은 API, 나머지는 CSV
    - method='csv': 모든 계정 CSV 생성 (기존 동작)
    - method='api': WING API 활성 계정만 API (비활성 계정 건너뜀)

    Returns:
        {"api": {계정명: {success, failed}}, "csv": {계정명: {filepath, count}}}
    """
    accounts = db.query(Account).filter(Account.is_active == True).all()
    if not accounts:
        logger.warning("등록된 계정이 없습니다.")
        return {"api": {}, "csv": {}}

    # 업로드 가능한 단권 상품
    products = db.query(Product).filter(
        Product.status == 'ready',
        Product.can_upload_single == True,
    ).all()

    if not products:
        logger.info("업로드할 상품이 없습니다.")
        return {"api": {}, "csv": {}}

    api_result = {}
    csv_result = {}
    franchise = FranchiseSync(db)

    for account in accounts:
        use_api = account.has_wing_api and method != 'csv'
        use_csv = not use_api and method != 'api'

        if not use_api and not use_csv:
            logger.info(f"  {account.account_name}: WING API 미활성, 건너뜀 (--upload-method api)")
            continue

        # 미등록 상품 필터링 (Listing 중복 체크)
        missing_products = []
        for product in products:
            existing = db.query(Listing).filter(
                Listing.account_id == account.id,
                Listing.isbn == product.isbn
            ).first()
            if not existing:
                missing_products.append(product)

        if not missing_products:
            logger.info(f"  {account.account_name}: 새로 업로드할 상품 없음")
            continue

        if use_api:
            # API 직접 등록 (FranchiseSync 재사용)
            logger.info(f"  {account.account_name}: API 등록 시작 ({len(missing_products)}개)...")
            result = franchise.upload_to_account(account, missing_products)
            api_result[account.account_name] = {
                "success": result["success"],
                "failed": result["failed"],
            }
        else:
            # CSV 생성 (기존 방식)
            account_products = []
            for product in missing_products:
                book = db.query(Book).filter(Book.isbn == product.isbn).first()
                if not book:
                    continue
                publisher = db.query(Publisher).get(book.publisher_id) if book.publisher_id else None
                account_products.append({
                    "product_name": book.title,
                    "original_price": book.list_price,
                    "sale_price": product.sale_price,
                    "isbn": book.isbn,
                    "publisher": publisher.name if publisher else "",
                    "shipping_policy": product.shipping_policy,
                    "net_margin": product.net_margin,
                })

            if not account_products:
                continue

            generator = CoupangCSVGenerator()
            filepath = generator.generate_csv(account_products, account.account_name)
            csv_result[account.account_name] = {
                "filepath": filepath,
                "count": len(account_products),
            }

            # CSV Listing 기록 — Listing은 sync_coupang_products에서 API 동기화로 생성됨
            # CSV 등록 후에는 다음 동기화 때 자동으로 매칭됨
            db.commit()
            logger.info(f"  {account.account_name}: {len(account_products)}개 상품 CSV 생성")

    return {"api": api_result, "csv": csv_result}


# ─────────────────────────────────────────────
# 메인 파이프라인
# ─────────────────────────────────────────────

def run_pipeline(publisher_names=None, max_results=20, dry_run=False, upload_method='auto'):
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
        print("\n[1/6] DB 초기화...")
        init_db()
        _migrate_account_columns()
        _migrate_product_registration_status()

        db = SessionLocal()

        try:
            # 시딩
            print("\n[2/6] 출판사 & 계정 등록...")
            with task_context("출판사/계정 시딩", "24개 출판사 + 5개 쿠팡 계정 등록 + WING API 연결"):
                seed_publishers(db)
                seed_accounts(db)

            # 알라딘 검색
            print(f"\n[3/6] 알라딘 API 도서 검색 (출판사당 최대 {max_results}개)...")
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
            print("\n[4/6] 마진 분석 & 상품 생성...")
            with task_context("마진 분석", "도서별 마진 계산 및 배송 정책 결정"):
                new_products, bundle_needed = analyze_and_create_products(db)

            # 묶음 생성
            if bundle_needed:
                print(f"\n  묶음 SKU 생성 ({len(bundle_needed)}개 저마진 도서)...")
                with task_context("묶음 SKU 생성", f"{len(bundle_needed)}개 저마진 도서 묶음 처리"):
                    create_bundle_skus(db, bundle_needed)

            # WING API 동기화 (기존 상품 sync)
            print("\n[5/6] 쿠팡 WING API 상품 동기화...")
            wing_synced = 0
            try:
                from scripts.sync_coupang_products import sync_account_products
                wing_accounts = db.query(Account).filter(
                    Account.is_active == True,
                    Account.wing_api_enabled == True,
                ).all()

                if wing_accounts:
                    with task_context("WING API 동기화", f"{len(wing_accounts)}개 계정 기존 상품 동기화"):
                        for acc in wing_accounts:
                            result = sync_account_products(db, acc, max_pages=0)
                            wing_synced += result["new"] + result["updated"]
                    logger.info(f"WING API 동기화: {wing_synced}개 상품 처리")
                else:
                    logger.info("WING API 활성 계정 없음, 동기화 건너뜀")
            except Exception as e:
                logger.warning(f"WING API 동기화 건너뜀 (오류: {e})")

            # 상품 등록 (API 우선 / CSV 폴백)
            method_label = {"auto": "API우선", "csv": "CSV만", "api": "API만"}
            print(f"\n[6/6] 계정별 상품 등록 ({method_label.get(upload_method, upload_method)})...")
            with task_context("상품 등록", f"계정별 상품 등록 (방식: {upload_method})"):
                upload_result = upload_products(db, method=upload_method)

            # 결과 요약
            elapsed = time.time() - start_time

            total_books = db.query(Book).count()
            total_products = db.query(Product).count()
            total_bundles = db.query(BundleSKU).count()
            total_listings = db.query(Listing).count()

            api_res = upload_result.get("api", {})
            csv_res = upload_result.get("csv", {})

            # Obsidian에 결과 기록
            upload_summary_lines = []
            if api_res:
                for acc_name, info in api_res.items():
                    upload_summary_lines.append(
                        f"- **{acc_name}** (API): 성공 {info['success']}개, 실패 {info['failed']}개"
                    )
            if csv_res:
                for acc_name, info in csv_res.items():
                    upload_summary_lines.append(
                        f"- **{acc_name}** (CSV): {info['count']}개 상품"
                    )
            if not upload_summary_lines:
                upload_summary_lines.append("- 새로 등록할 상품 없음 (모든 상품이 이미 등록됨)")

            upload_summary = "\n".join(upload_summary_lines)

            obs.log_to_daily(f"""**파이프라인 실행 결과**

| 항목 | 수량 |
|------|------|
| 도서 | {total_books}개 |
| 단권상품 | {total_products}개 |
| 묶음상품 | {total_bundles}개 |
| 등록현황 | {total_listings}개 |

**상품 등록 ({upload_method}):**
{upload_summary}

**소요 시간:** {elapsed:.1f}초""", "파이프라인 결과")

            print("\n" + "=" * 60)
            print("  파이프라인 완료")
            print("=" * 60)

            print(f"\n  DB 현황:")
            print(f"    도서:     {total_books}개")
            print(f"    단권상품: {total_products}개")
            print(f"    묶음상품: {total_bundles}개")
            print(f"    등록현황: {total_listings}개")

            if api_res:
                print(f"\n  API 등록 결과:")
                for acc_name, info in api_res.items():
                    print(f"    {acc_name}: 성공 {info['success']}개, 실패 {info['failed']}개")

            if csv_res:
                print(f"\n  생성된 CSV:")
                for acc_name, info in csv_res.items():
                    print(f"    {acc_name}: {info['count']}개 상품 → {info['filepath']}")

            if not api_res and not csv_res:
                print("\n  새로 등록할 상품 없음 (모든 상품이 이미 등록됨)")

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
    parser.add_argument(
        "--upload-method", choices=["auto", "csv", "api"], default="auto",
        help="업로드 방식: auto(API우선), csv(CSV만), api(API만)"
    )

    args = parser.parse_args()

    run_pipeline(
        publisher_names=args.publishers,
        max_results=args.max_results,
        dry_run=args.dry_run,
        upload_method=args.upload_method,
    )


if __name__ == "__main__":
    main()
