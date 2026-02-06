"""
쿠팡 WING API 상품 동기화 (2단계)
==================================
5개 계정의 기존 등록 상품을 API로 조회 → listings 테이블에 동기화

Stage 1: list_products(100개씩) → sellerProductId 목록 + 기본정보
Stage 2: get_product(id) × N개 → 전체 상세 JSON → DB 저장

사용법:
    python scripts/sync_coupang_products.py                    # 전체 5계정 동기화 (증분 상세)
    python scripts/sync_coupang_products.py --account 007-bm   # 특정 계정만
    python scripts/sync_coupang_products.py --quick             # 목록만 (Stage 1만)
    python scripts/sync_coupang_products.py --force             # 전체 상세 강제 재조회
    python scripts/sync_coupang_products.py --stale-hours 48    # 48시간 지난 것만 재조회
    python scripts/sync_coupang_products.py --max-pages 5       # 최대 5페이지만
    python scripts/sync_coupang_products.py --dry-run            # DB 저장 없이 조회만
"""
import sys
import os
import re
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta

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
from app.services.db_migration import SQLiteMigrator
from obsidian_logger import ObsidianLogger

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def _migrate_account_columns():
    """Account 테이블에 WING API 컬럼 추가 (SQLiteMigrator 사용)"""
    migrator = SQLiteMigrator(engine)
    migrator.add_columns_if_missing("accounts", {
        "vendor_id": "VARCHAR(20)",
        "wing_access_key": "VARCHAR(100)",
        "wing_secret_key": "VARCHAR(100)",
        "wing_api_enabled": "BOOLEAN DEFAULT 0",
        "outbound_shipping_code": "VARCHAR(50)",
        "return_center_code": "VARCHAR(50)",
    })


def _migrate_listing_detail_columns():
    """listings 테이블에 상세 동기화 컬럼 추가 (SQLiteMigrator 사용)"""
    migrator = SQLiteMigrator(engine)
    migrator.add_columns_if_missing("listings", {
        "brand": "VARCHAR(200)",
        "display_category_code": "VARCHAR(20)",
        "delivery_charge_type": "VARCHAR(20)",
        "maximum_buy_count": "INTEGER",
        "supply_price": "INTEGER",
        "delivery_charge": "INTEGER",
        "free_ship_over_amount": "INTEGER",
        "return_charge": "INTEGER",
        "raw_json": "TEXT",
        "detail_synced_at": "DATETIME",
    })


def _extract_isbn(product_data: dict) -> str:
    """
    쿠팡 상품 데이터에서 ISBN 추출

    우선순위:
    1. items[].attributes에서 ISBN 필드 (가장 정확)
    2. items[].barcode (바코드에 ISBN 13자리)
    3. items[].searchTags에서 ISBN 패턴
    4. sellerProductName에서 ISBN 패턴

    Returns:
        ISBN 문자열 또는 빈 문자열
    """
    isbn_pattern = re.compile(r'97[89]\d{10}')
    items = product_data.get("items", [])

    # 1) items[].attributes에서 ISBN 추출 (가장 정확)
    for item in items:
        attributes = item.get("attributes", [])
        if isinstance(attributes, list):
            for attr in attributes:
                attr_name = attr.get("attributeTypeName", "")
                attr_value = attr.get("attributeValueName", "")
                if attr_name == "ISBN" and attr_value and "상세" not in attr_value:
                    # ISBN 값이 숫자로만 구성되어 있는지 확인
                    cleaned = re.sub(r'[^0-9]', '', attr_value)
                    if len(cleaned) == 13 and cleaned.startswith(("978", "979")):
                        return cleaned

    # 2) items의 barcode에서 검색
    for item in items:
        barcode = str(item.get("barcode", ""))
        match = isbn_pattern.search(barcode)
        if match:
            return match.group()

    # 3) items의 vendorItemName 또는 searchTags에서 검색
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

    # 4) sellerProductName에서 검색
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


def _parse_detail_fields(detail_data: dict) -> dict:
    """상세 API 응답에서 DB 필드를 파싱"""
    result = {}

    # brand (루트 레벨)
    result["brand"] = detail_data.get("brand", "") or ""

    # displayCategoryCode
    result["display_category_code"] = str(detail_data.get("displayCategoryCode", "")) or ""

    # deliveryChargeType (배송비 유형)
    result["delivery_charge_type"] = detail_data.get("deliveryChargeType", "") or ""

    # 배송/반품 가격 (루트 레벨)
    result["delivery_charge"] = detail_data.get("deliveryCharge", None)
    result["free_ship_over_amount"] = detail_data.get("freeShipOverAmount", None)
    result["return_charge"] = detail_data.get("returnCharge", None)

    # items[0]에서 추출
    items = detail_data.get("items", [])
    if items:
        item = items[0]
        result["maximum_buy_count"] = item.get("maximumBuyCount", None)
        result["supply_price"] = item.get("supplyPrice", None)
        result["original_price"] = item.get("originalPrice", None)
        result["sale_price"] = item.get("salePrice", None)

        # attributes에서 ISBN, 출판사 추출
        result["isbn"] = None
        result["publisher"] = None
        attributes = item.get("attributes", [])
        if isinstance(attributes, list):
            for attr in attributes:
                attr_name = attr.get("attributeTypeName", "")
                attr_value = attr.get("attributeValueName", "")
                if attr_name == "ISBN" and attr_value and "상세" not in attr_value:
                    cleaned = re.sub(r'[^0-9]', '', attr_value)
                    if len(cleaned) == 13:
                        result["isbn"] = cleaned
                elif attr_name == "출판사" and attr_value and "상세" not in attr_value:
                    result["publisher"] = attr_value
    else:
        result["maximum_buy_count"] = None
        result["supply_price"] = None
        result["original_price"] = None
        result["sale_price"] = None
        result["isbn"] = None
        result["publisher"] = None

    return result


def create_wing_client(account: Account) -> CoupangWingClient:
    """Account 모델에서 WING API 클라이언트 생성"""
    if not account.has_wing_api:
        raise ValueError(f"{account.account_name}: WING API 정보가 없습니다")

    return CoupangWingClient(
        vendor_id=account.vendor_id,
        access_key=account.wing_access_key,
        secret_key=account.wing_secret_key,
    )


def _safe_commit(db, retries=5, delay=3):
    """SQLite lock 대비 rollback + 재시도 커밋"""
    for attempt in range(retries):
        try:
            db.commit()
            return
        except Exception as e:
            if "database is locked" in str(e) and attempt < retries - 1:
                logger.warning(f"  DB 잠금, {delay}초 후 재시도 ({attempt+1}/{retries})")
                db.rollback()
                time.sleep(delay)
            else:
                raise


def _fetch_product_detail(client: CoupangWingClient, seller_product_id: str) -> dict:
    """상품 상세 조회 (1회 재시도 포함)"""
    try:
        result = client.get_product(int(seller_product_id))
        # 응답에서 data 키 확인
        if isinstance(result, dict) and "data" in result:
            return result["data"] if isinstance(result["data"], dict) else result
        return result
    except CoupangWingError as e:
        # Rate limit이면 1초 대기 후 재시도
        if e.status_code == 429 or "RATE" in str(e.code).upper():
            logger.warning(f"    Rate limit, 1초 대기 후 재시도: {seller_product_id}")
            time.sleep(1)
            try:
                result = client.get_product(int(seller_product_id))
                if isinstance(result, dict) and "data" in result:
                    return result["data"] if isinstance(result["data"], dict) else result
                return result
            except CoupangWingError:
                pass
        raise


def sync_account_products(
    db, account: Account, max_pages: int = 0, dry_run: bool = False,
    quick: bool = False, force: bool = False, stale_hours: int = 24,
) -> dict:
    """
    단일 계정의 상품을 WING API로 조회하여 DB에 동기화

    Args:
        db: SQLAlchemy 세션
        account: 계정 모델
        max_pages: 목록 API 최대 페이지 수 (0=무제한)
        dry_run: True면 DB 저장 없이 조회만
        quick: True면 Stage 1만 (목록만)
        force: True면 모든 상품 상세 강제 재조회
        stale_hours: 상세 재조회 기준 시간 (기본 24)

    Returns:
        {"total", "new", "updated", "isbn_found", "isbn_missing", "detail_synced", "detail_skipped", "detail_error"}
    """
    result = {
        "total": 0, "new": 0, "updated": 0,
        "isbn_found": 0, "isbn_missing": 0,
        "detail_synced": 0, "detail_skipped": 0, "detail_error": 0,
    }

    try:
        client = create_wing_client(account)
    except ValueError as e:
        logger.error(str(e))
        return result

    logger.info(f"\n{'='*50}")
    logger.info(f"동기화: {account.account_name} (vendor_id={account.vendor_id})")
    logger.info(f"{'='*50}")

    # ── Stage 1: 상품 목록 조회 ──
    try:
        products = client.list_products(max_per_page=100, max_pages=max_pages)
    except CoupangWingError as e:
        logger.error(f"  상품 목록 조회 실패: {e}")
        return result

    result["total"] = len(products)
    logger.info(f"  [Stage 1] 총 {len(products)}개 상품 조회됨")

    if dry_run:
        for product_data in products:
            isbn = _extract_isbn(product_data)
            if isbn:
                result["isbn_found"] += 1
            else:
                result["isbn_missing"] += 1
        logger.info(f"  [DRY-RUN] ISBN 추출: {result['isbn_found']}개 성공, {result['isbn_missing']}개 실패")
        return result

    # 기존 listings를 한번에 로드 → dict로 룩업
    existing_listings = db.query(Listing).filter(
        Listing.account_id == account.id
    ).all()

    by_product_id = {}  # coupang_product_id → Listing
    by_isbn = {}        # isbn → Listing
    for lst in existing_listings:
        if lst.coupang_product_id:
            by_product_id[lst.coupang_product_id] = lst
        if lst.isbn:
            by_isbn[lst.isbn] = lst

    logger.info(f"  기존 DB listings: {len(existing_listings)}개 (product_id:{len(by_product_id)}, isbn:{len(by_isbn)})")

    now = datetime.utcnow()
    new_listings = []

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

        # dict 룩업 (DB 쿼리 없음)
        existing = by_product_id.get(seller_product_id)
        if not existing and isbn:
            existing = by_isbn.get(isbn)

        # 가격 추출
        items = product_data.get("items", [])
        sale_price = 0
        original_price = 0
        if items:
            sale_price = items[0].get("salePrice", 0) or 0
            original_price = items[0].get("originalPrice", 0) or 0

        if existing:
            existing.coupang_product_id = seller_product_id
            existing.coupang_status = coupang_status
            existing.product_name = product_name
            if vendor_item_id:
                existing.vendor_item_id = vendor_item_id
            if sale_price:
                existing.coupang_sale_price = sale_price
                existing.sale_price = sale_price
            if original_price:
                existing.original_price = original_price
            if isbn and not existing.isbn:
                existing.isbn = isbn
            existing.last_checked_at = now
            result["updated"] += 1
            # 새로 등록된 product_id도 룩업에 반영
            if seller_product_id:
                by_product_id[seller_product_id] = existing
        else:
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
                uploaded_at=now,
                last_checked_at=now,
            )
            new_listings.append(listing)
            result["new"] += 1
            # 룩업에 추가 (같은 배치 내 중복 방지)
            if seller_product_id:
                by_product_id[seller_product_id] = listing
            if isbn:
                by_isbn[isbn] = listing

    # 신규 listings 일괄 추가
    if new_listings:
        db.add_all(new_listings)

    _safe_commit(db)

    logger.info(f"  [Stage 1] 완료: 신규 {result['new']}개, 업데이트 {result['updated']}개")
    logger.info(f"  ISBN 추출: 성공 {result['isbn_found']}개, 실패 {result['isbn_missing']}개")

    # ── Stage 2: 상품 상세 조회 ──
    if quick:
        logger.info(f"  [Stage 2] --quick 모드: 상세 조회 생략")
        return result

    # 상세 조회 대상 선별
    stale_cutoff = now - timedelta(hours=stale_hours)
    detail_targets = []

    # by_product_id에서 모든 listing 수집 (신규 포함)
    all_listings = {pid: lst for pid, lst in by_product_id.items() if pid}

    for pid, lst in all_listings.items():
        if force:
            detail_targets.append((pid, lst))
        elif lst.detail_synced_at is None:
            detail_targets.append((pid, lst))
        elif lst.detail_synced_at < stale_cutoff:
            detail_targets.append((pid, lst))

    if not detail_targets:
        logger.info(f"  [Stage 2] 상세 조회 대상 없음 (모두 최신)")
        return result

    logger.info(f"  [Stage 2] 상세 조회 대상: {len(detail_targets)}개")

    for i, (pid, lst) in enumerate(detail_targets, 1):
        try:
            detail_data = _fetch_product_detail(client, pid)

            # 파싱된 필드 업데이트
            parsed = _parse_detail_fields(detail_data)
            lst.brand = parsed["brand"]
            lst.display_category_code = parsed["display_category_code"]
            lst.delivery_charge_type = parsed["delivery_charge_type"]
            lst.maximum_buy_count = parsed["maximum_buy_count"]
            if parsed["maximum_buy_count"] and parsed["maximum_buy_count"] > 0:
                lst.stock_quantity = parsed["maximum_buy_count"]
            lst.supply_price = parsed["supply_price"]
            lst.delivery_charge = parsed["delivery_charge"]
            lst.free_ship_over_amount = parsed["free_ship_over_amount"]
            lst.return_charge = parsed["return_charge"]

            # ISBN (attributes에서 추출한 것이 더 정확)
            # 단, 같은 account_id + isbn 조합이 이미 있으면 스킵 (UNIQUE 제약)
            if parsed["isbn"] and not lst.isbn:
                existing_with_isbn = db.query(Listing).filter(
                    Listing.account_id == lst.account_id,
                    Listing.isbn == parsed["isbn"],
                    Listing.id != lst.id
                ).first()
                if not existing_with_isbn:
                    lst.isbn = parsed["isbn"]

            # 가격 업데이트
            if parsed["original_price"] and parsed["original_price"] > 0:
                lst.original_price = parsed["original_price"]
            if parsed["sale_price"] and parsed["sale_price"] > 0:
                lst.coupang_sale_price = parsed["sale_price"]
                lst.sale_price = parsed["sale_price"]

            # onSale 상태 조회 (vendor_item_id가 있으면)
            vid = lst.vendor_item_id
            if vid:
                try:
                    inv_resp = client.get_item_inventory(int(vid))
                    inv_data = inv_resp.get("data", inv_resp) if isinstance(inv_resp, dict) else {}
                    on_sale = inv_data.get("onSale", True)
                    lst.coupang_status = "active" if on_sale else "paused"
                    # 재고도 업데이트
                    stock = inv_data.get("amountInStock")
                    if stock is not None:
                        lst.stock_quantity = stock
                except Exception:
                    pass  # 실패해도 상세 동기화는 계속

            # raw_json 저장
            lst.raw_json = json.dumps(detail_data, ensure_ascii=False)
            lst.detail_synced_at = now

            result["detail_synced"] += 1

            # 50건마다 중간 커밋 + 진행 로그
            if i % 50 == 0:
                _safe_commit(db)
                logger.info(f"    상세 진행: {i}/{len(detail_targets)} ({result['detail_synced']}성공, {result['detail_error']}실패)")

        except CoupangWingError as e:
            result["detail_error"] += 1
            logger.warning(f"    상세 조회 실패 [{pid}]: {e}")
        except Exception as e:
            result["detail_error"] += 1
            logger.warning(f"    상세 조회 오류 [{pid}]: {type(e).__name__}: {e}")

    # 최종 커밋
    _safe_commit(db)

    logger.info(f"  [Stage 2] 완료: 성공 {result['detail_synced']}개, 실패 {result['detail_error']}개, 스킵 {len(all_listings) - len(detail_targets)}개")

    return result


def _backfill_price_fields(db):
    """기존 raw_json에서 가격 필드 백필 (supply_price 등이 NULL인 레코드만)"""
    listings = db.query(Listing).filter(
        Listing.raw_json.isnot(None),
        Listing.supply_price.is_(None),
    ).all()

    if not listings:
        return 0

    count = 0
    for lst in listings:
        try:
            data = json.loads(lst.raw_json)
            parsed = _parse_detail_fields(data)
            lst.supply_price = parsed["supply_price"]
            lst.delivery_charge = parsed["delivery_charge"]
            lst.free_ship_over_amount = parsed["free_ship_over_amount"]
            lst.return_charge = parsed["return_charge"]
            count += 1
        except Exception:
            continue

    if count:
        _safe_commit(db)
        logger.info(f"  가격 필드 백필: {count}개 업데이트")

    return count


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


def run_sync(account_names=None, max_pages=0, dry_run=False,
             quick=False, force=False, stale_hours=24):
    """전체 동기화 실행"""
    obs = ObsidianLogger()

    mode_str = "quick(목록만)" if quick else ("force(전체 상세)" if force else f"증분(stale>{stale_hours}h)")

    print("\n" + "=" * 60)
    print("  쿠팡 WING API 상품 동기화 (2단계)")
    print(f"  모드: {mode_str}")
    print(f"  시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    init_db()
    _migrate_account_columns()
    _migrate_listing_detail_columns()
    db = SessionLocal()

    try:
        # WING API 크레덴셜 채우기
        populate_wing_credentials(db)

        # 기존 raw_json에서 새 가격 필드 백필
        _backfill_price_fields(db)

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
        total_result = {
            "total": 0, "new": 0, "updated": 0,
            "isbn_found": 0, "isbn_missing": 0,
            "detail_synced": 0, "detail_skipped": 0, "detail_error": 0,
        }

        for account in accounts:
            result = sync_account_products(
                db, account, max_pages=max_pages, dry_run=dry_run,
                quick=quick, force=force, stale_hours=stale_hours,
            )

            for key in total_result:
                total_result[key] += result[key]

        # 결과 요약
        total_listings = db.query(Listing).count()
        detail_filled = db.query(Listing).filter(Listing.raw_json.isnot(None)).count()

        print("\n" + "=" * 60)
        print("  동기화 결과")
        print("=" * 60)
        print(f"  [Stage 1] 총 조회: {total_result['total']}개")
        print(f"  [Stage 1] 신규: {total_result['new']}개 / 업데이트: {total_result['updated']}개")
        print(f"  [Stage 1] ISBN 성공: {total_result['isbn_found']}개 / 실패: {total_result['isbn_missing']}개")
        if not quick:
            print(f"  [Stage 2] 상세 성공: {total_result['detail_synced']}개 / 실패: {total_result['detail_error']}개")
        print(f"  DB 총 Listings: {total_listings}개 (상세 보유: {detail_filled}개)")
        print("=" * 60)

        # Obsidian 로그
        detail_line = ""
        if not quick:
            detail_line = f"\n| 상세 성공 | {total_result['detail_synced']}개 |\n| 상세 실패 | {total_result['detail_error']}개 |"

        obs.log_to_daily(f"""**WING API 상품 동기화 완료** ({mode_str})

| 항목 | 수량 |
|------|------|
| 조회 | {total_result['total']}개 |
| 신규 | {total_result['new']}개 |
| 업데이트 | {total_result['updated']}개 |
| ISBN 성공 | {total_result['isbn_found']}개 |
| ISBN 실패 | {total_result['isbn_missing']}개 |{detail_line}
| DB Listings | {total_listings}개 |
| 상세 보유 | {detail_filled}개 |""", "WING API 동기화")

    except Exception as e:
        logger.error(f"동기화 오류: {e}", exc_info=True)
        obs.log_to_daily(f"**동기화 오류:** `{type(e).__name__}: {e}`", "WING API 동기화 실패")
        db.rollback()
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="쿠팡 WING API 상품 동기화 (2단계)")
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
    parser.add_argument(
        "--quick", action="store_true",
        help="목록만 동기화 (Stage 1만, 상세 조회 생략)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="모든 상품 상세 강제 재조회"
    )
    parser.add_argument(
        "--stale-hours", type=int, default=24,
        help="상세 재조회 기준 시간 (기본: 24시간)"
    )

    args = parser.parse_args()

    run_sync(
        account_names=args.account,
        max_pages=args.max_pages,
        dry_run=args.dry_run,
        quick=args.quick,
        force=args.force,
        stale_hours=args.stale_hours,
    )


if __name__ == "__main__":
    main()
