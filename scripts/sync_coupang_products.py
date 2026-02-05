"""
쿠팡 WING API 상품 동기화
==========================
5개 계정의 기존 등록 상품을 API로 조회 → listings 테이블에 동기화

사용법:
    python scripts/sync_coupang_products.py                    # 전체 5계정 동기화
    python scripts/sync_coupang_products.py --account 007-bm   # 특정 계정만
    python scripts/sync_coupang_products.py --max-pages 5      # 최대 5페이지만
    python scripts/sync_coupang_products.py --dry-run           # DB 저장 없이 조회만
"""
import sys
import os
import re
import argparse
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
from app.database import SessionLocal, init_db, engine
from app.models.account import Account
from app.models.listing import Listing
from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
from app.constants import WING_ACCOUNT_ENV_MAP
from obsidian_logger import ObsidianLogger

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def _migrate_account_columns():
    """Account 테이블에 WING API 컬럼 추가 (SQLite ALTER TABLE)"""
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


def _extract_isbn(product_data: dict) -> str:
    """
    쿠팡 상품 데이터에서 ISBN 추출

    우선순위:
    1. items[].barcode (바코드에 ISBN 13자리)
    2. items[].searchTags에서 ISBN 패턴
    3. sellerProductName에서 ISBN 패턴

    Returns:
        ISBN 문자열 또는 빈 문자열
    """
    isbn_pattern = re.compile(r'97[89]\d{10}')

    # 1) items의 barcode에서 검색
    items = product_data.get("items", [])
    for item in items:
        barcode = str(item.get("barcode", ""))
        match = isbn_pattern.search(barcode)
        if match:
            return match.group()

    # 2) items의 vendorItemName 또는 searchTags에서 검색
    for item in items:
        # searchTags
        search_tags = item.get("searchTags", [])
        if isinstance(search_tags, list):
            for tag in search_tags:
                match = isbn_pattern.search(str(tag))
                if match:
                    return match.group()

        # vendorItemName
        vendor_name = str(item.get("vendorItemName", ""))
        match = isbn_pattern.search(vendor_name)
        if match:
            return match.group()

    # 3) sellerProductName에서 검색
    product_name = str(product_data.get("sellerProductName", ""))
    match = isbn_pattern.search(product_name)
    if match:
        return match.group()

    return ""


def _get_vendor_item_id(product_data: dict) -> str:
    """상품 데이터에서 vendorItemId 추출"""
    items = product_data.get("items", [])
    if items:
        return str(items[0].get("vendorItemId", ""))
    return ""


def _get_product_status(product_data: dict) -> str:
    """상품 상태를 listings 테이블 포맷으로 변환"""
    status = product_data.get("statusName", product_data.get("status", ""))
    status_map = {
        "판매중": "active",
        "승인완료": "active",
        "APPROVE": "active",
        "판매중지": "paused",
        "SUSPEND": "paused",
        "품절": "sold_out",
        "SOLDOUT": "sold_out",
        "승인반려": "rejected",
        "삭제": "deleted",
        "DELETE": "deleted",
        "승인대기": "pending",
    }
    return status_map.get(status, "pending")


def create_wing_client(account: Account) -> CoupangWingClient:
    """Account 모델에서 WING API 클라이언트 생성"""
    if not account.has_wing_api:
        raise ValueError(f"{account.account_name}: WING API 정보가 없습니다")

    return CoupangWingClient(
        vendor_id=account.vendor_id,
        access_key=account.wing_access_key,
        secret_key=account.wing_secret_key,
    )


def sync_account_products(db, account: Account, max_pages: int = 0, dry_run: bool = False) -> dict:
    """
    단일 계정의 상품을 WING API로 조회하여 DB에 동기화

    Returns:
        {"total": int, "new": int, "updated": int, "isbn_found": int, "isbn_missing": int}
    """
    result = {"total": 0, "new": 0, "updated": 0, "isbn_found": 0, "isbn_missing": 0}

    try:
        client = create_wing_client(account)
    except ValueError as e:
        logger.error(str(e))
        return result

    logger.info(f"\n{'='*50}")
    logger.info(f"동기화: {account.account_name} (vendor_id={account.vendor_id})")
    logger.info(f"{'='*50}")

    # API 연결 테스트
    if not client.test_connection():
        logger.error(f"  API 연결 실패, 건너뜀")
        return result

    # 전체 상품 목록 조회
    try:
        products = client.list_products(max_per_page=50, max_pages=max_pages)
    except CoupangWingError as e:
        logger.error(f"  상품 목록 조회 실패: {e}")
        return result

    result["total"] = len(products)
    logger.info(f"  총 {len(products)}개 상품 조회됨")

    if dry_run:
        # ISBN 추출 통계만 수집
        for product_data in products:
            isbn = _extract_isbn(product_data)
            if isbn:
                result["isbn_found"] += 1
            else:
                result["isbn_missing"] += 1
        logger.info(f"  [DRY-RUN] ISBN 추출: {result['isbn_found']}개 성공, {result['isbn_missing']}개 실패")
        return result

    # DB에 upsert
    for product_data in products:
        seller_product_id = str(product_data.get("sellerProductId", ""))
        isbn = _extract_isbn(product_data)
        vendor_item_id = _get_vendor_item_id(product_data)
        coupang_status = _get_product_status(product_data)
        product_name = product_data.get("sellerProductName", "")

        if isbn:
            result["isbn_found"] += 1
        else:
            result["isbn_missing"] += 1

        # 기존 Listing 확인 (coupang_product_id 또는 isbn으로)
        existing = None
        if seller_product_id:
            existing = db.query(Listing).filter(
                Listing.account_id == account.id,
                Listing.coupang_product_id == seller_product_id,
            ).first()

        if not existing and isbn:
            existing = db.query(Listing).filter(
                Listing.account_id == account.id,
                Listing.isbn == isbn,
            ).first()

        # 상품 정보 추출
        items = product_data.get("items", [])
        sale_price = 0
        original_price = 0
        if items:
            sale_price = items[0].get("salePrice", 0) or 0
            original_price = items[0].get("originalPrice", 0) or 0

        if existing:
            # 업데이트
            existing.coupang_product_id = seller_product_id
            existing.coupang_status = coupang_status
            existing.product_name = product_name
            if sale_price:
                existing.sale_price = sale_price
            if original_price:
                existing.original_price = original_price
            if isbn and not existing.isbn:
                existing.isbn = isbn
            existing.last_checked_at = datetime.utcnow()
            result["updated"] += 1
        else:
            # 신규 생성
            listing = Listing(
                account_id=account.id,
                product_type="single",
                isbn=isbn if isbn else None,
                coupang_product_id=seller_product_id,
                coupang_status=coupang_status,
                sale_price=sale_price,
                original_price=original_price,
                product_name=product_name,
                shipping_policy="free",
                upload_method="api_sync",
                uploaded_at=datetime.utcnow(),
                last_checked_at=datetime.utcnow(),
            )
            db.add(listing)
            result["new"] += 1

    db.commit()

    logger.info(f"  동기화 완료: 신규 {result['new']}개, 업데이트 {result['updated']}개")
    logger.info(f"  ISBN 추출: 성공 {result['isbn_found']}개, 실패 {result['isbn_missing']}개")

    return result


def populate_wing_credentials(db):
    """
    .env에서 WING API 크레덴셜을 읽어 Account 레코드에 저장
    (이미 값이 있으면 건너뜀)
    """
    updated = 0

    for account_name, env_prefix in WING_ACCOUNT_ENV_MAP.items():
        vendor_id = os.getenv(f"{env_prefix}_VENDOR_ID")
        access_key = os.getenv(f"{env_prefix}_ACCESS_KEY")
        secret_key = os.getenv(f"{env_prefix}_SECRET_KEY")

        if not all([vendor_id, access_key, secret_key]):
            continue

        account = db.query(Account).filter(
            Account.account_name == account_name
        ).first()

        if not account:
            logger.warning(f"계정 없음: {account_name} (DB에 먼저 등록 필요)")
            continue

        if account.has_wing_api:
            continue

        account.vendor_id = vendor_id
        account.wing_access_key = access_key
        account.wing_secret_key = secret_key
        account.wing_api_enabled = True
        updated += 1

    db.commit()
    if updated:
        logger.info(f"WING API 크레덴셜 {updated}개 계정에 등록")
    return updated


def run_sync(account_names=None, max_pages=0, dry_run=False):
    """전체 동기화 실행"""
    obs = ObsidianLogger()

    print("\n" + "=" * 60)
    print("  쿠팡 WING API 상품 동기화")
    print(f"  시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    init_db()
    _migrate_account_columns()
    db = SessionLocal()

    try:
        # WING API 크레덴셜 채우기
        populate_wing_credentials(db)

        # 동기화 대상 계정 조회
        query = db.query(Account).filter(
            Account.is_active == True,
            Account.wing_api_enabled == True,
        )

        if account_names:
            query = query.filter(Account.account_name.in_(account_names))

        accounts = query.all()

        if not accounts:
            print("\n  WING API가 활성화된 계정이 없습니다.")
            print("  .env에 COUPANG_*_VENDOR_ID, _ACCESS_KEY, _SECRET_KEY를 확인하세요.")
            return

        print(f"\n  동기화 대상: {len(accounts)}개 계정")
        for acc in accounts:
            print(f"    - {acc.account_name} (vendor_id={acc.vendor_id})")

        # 계정별 동기화
        total_result = {"total": 0, "new": 0, "updated": 0, "isbn_found": 0, "isbn_missing": 0}

        for account in accounts:
            result = sync_account_products(db, account, max_pages=max_pages, dry_run=dry_run)

            for key in total_result:
                total_result[key] += result[key]

        # 결과 요약
        total_listings = db.query(Listing).count()

        print("\n" + "=" * 60)
        print("  동기화 결과")
        print("=" * 60)
        print(f"  총 조회: {total_result['total']}개")
        print(f"  신규 등록: {total_result['new']}개")
        print(f"  업데이트: {total_result['updated']}개")
        print(f"  ISBN 추출 성공: {total_result['isbn_found']}개")
        print(f"  ISBN 추출 실패: {total_result['isbn_missing']}개")
        print(f"  DB 총 Listings: {total_listings}개")
        print("=" * 60)

        # Obsidian 로그
        obs.log_to_daily(f"""**WING API 상품 동기화 완료**

| 항목 | 수량 |
|------|------|
| 조회 | {total_result['total']}개 |
| 신규 | {total_result['new']}개 |
| 업데이트 | {total_result['updated']}개 |
| ISBN 성공 | {total_result['isbn_found']}개 |
| ISBN 실패 | {total_result['isbn_missing']}개 |
| DB Listings | {total_listings}개 |""", "WING API 동기화")

    except Exception as e:
        logger.error(f"동기화 오류: {e}", exc_info=True)
        obs.log_to_daily(f"**동기화 오류:** `{type(e).__name__}: {e}`", "WING API 동기화 실패")
        db.rollback()
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="쿠팡 WING API 상품 동기화")
    parser.add_argument(
        "--account", nargs="+",
        help="특정 계정만 동기화 (예: --account 007-bm 007-book)"
    )
    parser.add_argument(
        "--max-pages", type=int, default=0,
        help="계정당 최대 페이지 수 (기본: 0=무제한)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="DB 저장 없이 조회만"
    )

    args = parser.parse_args()

    run_sync(
        account_names=args.account,
        max_pages=args.max_pages,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
