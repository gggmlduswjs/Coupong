"""
세트상품 ISBN/수량 수정 스크립트
================================
셀러허브에서 수동 등록한 세트상품의 items[] 배열과 unitCount가 올바르게 설정되지 않은 경우,
WING API PUT(update_product)으로 기존 상품을 수정한다.

모드 A (기본): unitCount만 수정 — 기존 items[0]의 unitCount를 세트 권수(N)로 변경
모드 B (--multi-item): items[] 개별 분리 — 각 ISBN별 별도 item으로 분리

사용법:
  # 드라이런 (기본) — 변경사항 미리보기만
  python scripts/fix_bundle_items.py --product-id 16012345678

  # 특정 계정 묶음 전체 분석
  python scripts/fix_bundle_items.py --account 007-book --all-bundles

  # unitCount만 수정 (실행)
  python scripts/fix_bundle_items.py --product-id 16012345678 --execute

  # items[] 개별 분리 (실행)
  python scripts/fix_bundle_items.py --product-id 16012345678 --multi-item --execute

  # raw_json 없으면 API에서 새로 조회
  python scripts/fix_bundle_items.py --all-bundles --refresh --limit 10
"""
import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.listing import Listing
from app.models.bundle_sku import BundleSKU
from app.models.book import Book
from app.models.account import Account
from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
from uploaders.coupang_api_uploader import _dedupe_attributes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# 쿠팡 바코드로 사용 가능한 ISBN-13 패턴
_VALID_BARCODE_RE = re.compile(r'^97[89]\d{10}$')

SELLER_PRODUCTS_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"


# ─── ISBN 목록 결정 ─────────────────────────────────────────────

def resolve_isbns(listing: Listing, db) -> List[str]:
    """
    리스팅에서 ISBN 목록 추출 (우선순위):
    1. bundle_id → BundleSKU.get_isbns()
    2. listing.isbn (쉼표 구분)
    3. raw_json의 items[].barcode / searchTags에서 추출
    """
    # 1) BundleSKU에서
    if listing.bundle_id:
        bundle = db.query(BundleSKU).filter(BundleSKU.id == listing.bundle_id).first()
        if bundle:
            isbns = bundle.get_isbns()
            if isbns:
                return isbns

    # 2) listing.isbn (쉼표 구분)
    if listing.isbn and ',' in listing.isbn:
        isbns = [i.strip() for i in listing.isbn.split(',') if i.strip()]
        if len(isbns) > 1:
            return isbns

    # 3) raw_json에서 추출
    if listing.raw_json:
        try:
            data = json.loads(listing.raw_json)
            product = data.get("data", data)
            items = product.get("items", [])
            isbns = []
            for item in items:
                barcode = item.get("barcode", "")
                if barcode and _VALID_BARCODE_RE.match(barcode):
                    isbns.append(barcode)
                # searchTags에서도 ISBN 추출 시도
                if not barcode or not _VALID_BARCODE_RE.match(barcode):
                    for tag in item.get("searchTags", []):
                        val = tag if isinstance(tag, str) else tag.get("text", "")
                        if _VALID_BARCODE_RE.match(val) and val not in isbns:
                            isbns.append(val)
            if isbns:
                return isbns
        except Exception:
            pass

    # 단일 ISBN이라도 반환
    if listing.isbn:
        return [listing.isbn.strip()]

    return []


def get_product_data(listing: Listing, client: Optional[CoupangWingClient], refresh: bool) -> Optional[Dict]:
    """상품 데이터 조회 (raw_json 파싱 또는 API 호출)"""
    # refresh 모드면 API에서 새로 조회
    if refresh and client and listing.coupang_product_id:
        try:
            result = client.get_product(int(listing.coupang_product_id))
            product = result.get("data", result)
            return product
        except Exception as e:
            logger.warning(f"  API 조회 실패 (product_id={listing.coupang_product_id}): {e}")

    # raw_json 파싱
    if listing.raw_json:
        try:
            data = json.loads(listing.raw_json)
            return data.get("data", data)
        except Exception:
            pass

    # raw_json 없으면 API에서 조회
    if client and listing.coupang_product_id:
        try:
            result = client.get_product(int(listing.coupang_product_id))
            return result.get("data", result)
        except Exception as e:
            logger.warning(f"  API 조회 실패 (product_id={listing.coupang_product_id}): {e}")

    return None


# ─── 모드 A: unitCount만 수정 ───────────────────────────────────

def build_payload_unit_count(product: Dict, isbns: List[str]) -> Dict:
    """
    모드 A: 기존 items[0]의 unitCount를 세트 권수(N)로 변경,
    barcode에 첫 번째 ISBN 설정
    """
    items = product.get("items", [])
    if not items:
        raise ValueError("items가 비어있음")

    n = len(isbns)
    first_isbn = isbns[0] if isbns else ""

    # 기존 item 복사 후 수정
    orig_item = items[0]
    new_item = _build_item_payload(orig_item)
    new_item["unitCount"] = n
    if first_isbn and _VALID_BARCODE_RE.match(first_isbn):
        new_item["barcode"] = first_isbn
        new_item["emptyBarcode"] = False
        new_item["emptyBarcodeReason"] = ""

    payload = _build_product_payload(product, [new_item])
    return payload


# ─── 모드 B: items[] 개별 분리 ──────────────────────────────────

def build_payload_multi_item(product: Dict, isbns: List[str], db) -> Dict:
    """
    모드 B: 각 ISBN별 별도 item으로 분리
    - 첫 번째 아이템은 기존 sellerProductItemId 유지
    - 나머지 N-1개는 sellerProductItemId 없이 새로 추가
    """
    items = product.get("items", [])
    if not items:
        raise ValueError("items가 비어있음")

    orig_item = items[0]
    new_items = []

    for i, isbn in enumerate(isbns):
        # DB에서 Book 조회하여 개별 가격 확인
        book = db.query(Book).filter(Book.isbn == isbn).first()

        if book:
            list_price = book.list_price
            sale_price = int(list_price * 0.9)  # 도서정가제
            item_name = book.title[:150]
        else:
            # Book 없으면 기존 item 가격 유지
            list_price = orig_item.get("originalPrice", 0)
            sale_price = orig_item.get("salePrice", 0)
            item_name = orig_item.get("itemName", "")[:150]

        item_payload = _build_item_payload(orig_item)
        item_payload["itemName"] = item_name
        item_payload["originalPrice"] = list_price
        item_payload["salePrice"] = sale_price
        item_payload["unitCount"] = 1

        # barcode 설정
        if isbn and _VALID_BARCODE_RE.match(isbn):
            item_payload["barcode"] = isbn
            item_payload["emptyBarcode"] = False
            item_payload["emptyBarcodeReason"] = ""
        else:
            item_payload["barcode"] = ""
            item_payload["emptyBarcode"] = True
            item_payload["emptyBarcodeReason"] = "도서 바코드 없음"

        item_payload["modelNo"] = isbn or ""
        item_payload["externalVendorSku"] = isbn or ""

        if i == 0:
            # 첫 번째: 기존 sellerProductItemId 유지
            item_payload["sellerProductItemId"] = orig_item["sellerProductItemId"]
        else:
            # 나머지: sellerProductItemId 생략 (새로 추가)
            item_payload.pop("sellerProductItemId", None)

        new_items.append(item_payload)

    payload = _build_product_payload(product, new_items)
    return payload


# ─── 공통 페이로드 빌더 ─────────────────────────────────────────

def _build_item_payload(item: Dict) -> Dict:
    """기존 item 데이터로부터 PUT용 item 페이로드 구성"""
    return {
        "sellerProductItemId": item.get("sellerProductItemId"),
        "itemName": item.get("itemName", ""),
        "originalPrice": item.get("originalPrice", 0),
        "salePrice": item.get("salePrice", 0),
        "maximumBuyCount": item.get("maximumBuyCount", 1000),
        "maximumBuyForPerson": item.get("maximumBuyForPerson", 0),
        "maximumBuyForPersonPeriod": item.get("maximumBuyForPersonPeriod", 1),
        "outboundShippingTimeDay": item.get("outboundShippingTimeDay", 1),
        "unitCount": item.get("unitCount", 1),
        "adultOnly": item.get("adultOnly", "EVERYONE"),
        "taxType": item.get("taxType", "FREE"),
        "parallelImported": item.get("parallelImported", "NOT_PARALLEL_IMPORTED"),
        "overseasPurchased": item.get("overseasPurchased", "NOT_OVERSEAS_PURCHASED"),
        "pccNeeded": item.get("pccNeeded", False),
        "offerCondition": item.get("offerCondition", "NEW"),
        "barcode": item.get("barcode", ""),
        "emptyBarcode": item.get("emptyBarcode", True),
        "emptyBarcodeReason": item.get("emptyBarcodeReason", ""),
        "modelNo": item.get("modelNo", ""),
        "externalVendorSku": item.get("externalVendorSku", ""),
        "searchTags": item.get("searchTags", []),
        "images": item.get("images", []),
        "notices": item.get("notices", []),
        "attributes": _dedupe_attributes(item.get("attributes", [])),
        "contents": item.get("contents", []),
        "certifications": item.get("certifications", []),
    }


def _build_product_payload(product: Dict, items: List[Dict]) -> Dict:
    """PUT용 상품 페이로드 구성 (update_product_names.py 패턴)"""
    pid = int(product.get("sellerProductId", 0))
    return {
        "sellerProductId": pid,
        "displayCategoryCode": product["displayCategoryCode"],
        "sellerProductName": product.get("sellerProductName", ""),
        "vendorId": product.get("vendorId", ""),
        "saleStartedAt": product.get("saleStartedAt", ""),
        "saleEndedAt": product.get("saleEndedAt", "2099-12-31T00:00:00"),
        "displayProductName": product.get("displayProductName", ""),
        "brand": product.get("brand", ""),
        "generalProductName": product.get("generalProductName", ""),
        "productGroup": product.get("productGroup", ""),
        "deliveryMethod": product["deliveryMethod"],
        "deliveryCompanyCode": product.get("deliveryCompanyCode", "HANJIN"),
        "deliveryChargeType": product["deliveryChargeType"],
        "deliveryCharge": product["deliveryCharge"],
        "freeShipOverAmount": product.get("freeShipOverAmount", 0),
        "deliveryChargeOnReturn": product.get("deliveryChargeOnReturn", 0),
        "remoteAreaDeliverable": product.get("remoteAreaDeliverable", "N"),
        "unionDeliveryType": product.get("unionDeliveryType", "UNION_DELIVERY"),
        "returnCenterCode": product["returnCenterCode"],
        "returnChargeName": product.get("returnChargeName", ""),
        "companyContactNumber": product.get("companyContactNumber", ""),
        "returnZipCode": product.get("returnZipCode", ""),
        "returnAddress": product.get("returnAddress", ""),
        "returnAddressDetail": product.get("returnAddressDetail", ""),
        "returnCharge": product.get("returnCharge", 0),
        "outboundShippingPlaceCode": product["outboundShippingPlaceCode"],
        "vendorUserId": product.get("vendorUserId", ""),
        "requested": True,
        "manufacture": product.get("manufacture", ""),
        "items": items,
    }


# ─── API 호출 ───────────────────────────────────────────────────

def execute_update(client: CoupangWingClient, payload: Dict) -> Tuple[bool, str]:
    """PUT API 호출"""
    try:
        result = client._request("PUT", SELLER_PRODUCTS_PATH, data=payload)
        code = result.get("code", "")
        if code == "SUCCESS":
            return True, "성공"

        msg = str(result.get("message", result))
        if "초과" in msg and "구매옵션" in msg:
            return False, "QUOTA_EXCEEDED"
        return False, f"응답: {msg[:200]}"

    except CoupangWingError as e:
        err_msg = str(e)
        if "초과" in err_msg and "구매옵션" in err_msg:
            return False, "QUOTA_EXCEEDED"
        return False, f"API 오류: {e}"
    except Exception as e:
        return False, f"예외: {e}"


# ─── Diff 출력 ──────────────────────────────────────────────────

def print_diff(product: Dict, isbns: List[str], multi_item: bool):
    """변경 전/후 비교 출력"""
    items = product.get("items", [])
    name = product.get("sellerProductName", "?")[:50]

    logger.info(f"  상품명: {name}")
    logger.info(f"  목표 ISBN ({len(isbns)}권): {', '.join(isbns)}")

    # 현재 상태
    logger.info(f"  [현재] items 수: {len(items)}")
    for i, item in enumerate(items):
        uc = item.get("unitCount", "?")
        bc = item.get("barcode", "(없음)")
        iname = item.get("itemName", "?")[:40]
        logger.info(f"    item[{i}]: unitCount={uc}, barcode={bc}, name={iname}")

    # 변경 후
    if multi_item:
        logger.info(f"  [변경후] items 수: {len(isbns)} (개별 분리)")
        for i, isbn in enumerate(isbns):
            logger.info(f"    item[{i}]: unitCount=1, barcode={isbn}")
    else:
        logger.info(f"  [변경후] items 수: 1 (unitCount 변경)")
        logger.info(f"    item[0]: unitCount={len(isbns)}, barcode={isbns[0] if isbns else '?'}")


# ─── 대상 리스팅 조회 ───────────────────────────────────────────

def get_target_listings(db, args, account: Account) -> List[Listing]:
    """대상 리스팅 목록 조회"""
    query = db.query(Listing).filter(
        Listing.account_id == account.id,
        Listing.coupang_product_id != None,
    )

    if args.product_id:
        query = query.filter(Listing.coupang_product_id == args.product_id)
    elif args.all_bundles:
        # bundle_id 있거나 isbn에 쉼표 포함 (product_type 삭제됨)
        from sqlalchemy import or_
        query = query.filter(
            or_(
                Listing.bundle_id.isnot(None),
                Listing.isbn.like('%,%'),
            )
        )
    else:
        logger.error("--product-id 또는 --all-bundles 필요")
        return []

    listings = query.all()

    if args.limit and args.limit > 0:
        listings = listings[:args.limit]

    return listings


# ─── 메인 ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="세트상품 ISBN/수량 수정")
    # 대상 선택
    parser.add_argument("--product-id", type=str, help="특정 쿠팡 상품 ID")
    parser.add_argument("--all-bundles", action="store_true", help="bundle 타입 또는 ISBN 쉼표 포함 리스팅 전체")
    parser.add_argument("--account", type=str, help="특정 계정만 (예: 007-book)")
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 상품 수 (0=전체)")

    # 모드
    parser.add_argument("--multi-item", action="store_true", help="모드 B: items[] 개별 분리 (기본은 unitCount만 수정)")

    # 실행
    parser.add_argument("--execute", action="store_true", help="실제 API 호출 (없으면 드라이런)")
    parser.add_argument("--refresh", action="store_true", help="raw_json 대신 API에서 새로 조회")
    parser.add_argument("--delay", type=float, default=0.15, help="API 호출 간 대기 (초)")

    args = parser.parse_args()

    if not args.product_id and not args.all_bundles:
        parser.error("--product-id 또는 --all-bundles 중 하나 필요")

    dry_run = not args.execute
    if dry_run:
        logger.info("=== 드라이런 모드 (API 호출 없음) ===\n")
    else:
        logger.info("=== 실행 모드 (API 호출 실행) ===\n")

    db = SessionLocal()

    try:
        # 대상 계정
        account_query = db.query(Account).filter(Account.wing_api_enabled == True)
        if args.account:
            account_query = account_query.filter(Account.account_name == args.account)
        accounts = account_query.all()

        if not accounts:
            logger.error("대상 계정 없음")
            return

        logger.info(f"대상 계정: {[a.account_name for a in accounts]}")

        total_checked = 0
        total_changed = 0
        total_skipped = 0
        total_failed = 0
        quota_hit_global = False

        for account in accounts:
            if quota_hit_global:
                break

            logger.info(f"\n{'='*60}")
            logger.info(f"계정: {account.account_name} (vendor_id={account.vendor_id})")
            logger.info(f"{'='*60}")

            listings = get_target_listings(db, args, account)
            logger.info(f"  대상 리스팅: {len(listings)}개")

            if not listings:
                continue

            # WING API 클라이언트
            client = None
            if not dry_run or args.refresh:
                client = CoupangWingClient(
                    vendor_id=account.vendor_id,
                    access_key=account.wing_access_key,
                    secret_key=account.wing_secret_key,
                )

            for listing in listings:
                if quota_hit_global:
                    break

                total_checked += 1
                pid = listing.coupang_product_id
                logger.info(f"\n--- [{total_checked}] product_id={pid} ---")

                # 1) 상품 데이터 조회
                product = get_product_data(listing, client, args.refresh)
                if not product:
                    logger.warning(f"  상품 데이터 없음 (raw_json/API 모두 실패)")
                    total_skipped += 1
                    continue

                items = product.get("items", [])
                if not items:
                    logger.warning(f"  items가 비어있음")
                    total_skipped += 1
                    continue

                # 2) ISBN 목록 결정
                isbns = resolve_isbns(listing, db)
                if not isbns or len(isbns) < 2:
                    logger.info(f"  ISBN {len(isbns)}개 — 세트가 아닌 단권 (스킵)")
                    total_skipped += 1
                    continue

                # 3) 변경 필요 여부 확인
                current_unit_count = items[0].get("unitCount", 1)
                current_item_count = len(items)
                need_change = False

                if args.multi_item:
                    # 모드 B: item 수가 ISBN 수와 다르면 변경 필요
                    if current_item_count != len(isbns):
                        need_change = True
                    else:
                        # item 수는 같지만 barcode가 다를 수 있음
                        for i, isbn in enumerate(isbns):
                            if i < len(items) and items[i].get("barcode", "") != isbn:
                                need_change = True
                                break
                else:
                    # 모드 A: unitCount가 다르면 변경 필요
                    if current_unit_count != len(isbns):
                        need_change = True
                    # barcode 확인
                    current_barcode = items[0].get("barcode", "")
                    if current_barcode != isbns[0]:
                        need_change = True

                if not need_change:
                    logger.info(f"  이미 올바른 상태 (스킵)")
                    total_skipped += 1
                    continue

                # 4) Diff 출력
                print_diff(product, isbns, args.multi_item)

                # 5) 페이로드 구성
                try:
                    if args.multi_item:
                        payload = build_payload_multi_item(product, isbns, db)
                    else:
                        payload = build_payload_unit_count(product, isbns)
                except Exception as e:
                    logger.error(f"  페이로드 구성 실패: {e}")
                    total_failed += 1
                    continue

                # 6) 실행 또는 드라이런
                if dry_run:
                    logger.info(f"  → 드라이런: 변경 예정 (--execute로 실행)")
                    total_changed += 1
                else:
                    success, msg = execute_update(client, payload)
                    if success:
                        logger.info(f"  → 성공!")
                        total_changed += 1
                    else:
                        if msg == "QUOTA_EXCEEDED":
                            logger.warning(f"  → 쿼터 초과! 전체 중단.")
                            total_failed += 1
                            quota_hit_global = True
                        else:
                            logger.warning(f"  → 실패: {msg}")
                            total_failed += 1

                    time.sleep(args.delay)

        # 결과 요약
        logger.info(f"\n{'='*60}")
        mode_label = "모드 B (items 분리)" if args.multi_item else "모드 A (unitCount)"
        run_label = "실행" if not dry_run else "드라이런"
        logger.info(f"세트상품 수정 완료 [{mode_label}] [{run_label}]")
        logger.info(f"  확인: {total_checked}")
        logger.info(f"  변경{'예정' if dry_run else ''}: {total_changed}")
        logger.info(f"  스킵: {total_skipped}")
        logger.info(f"  실패: {total_failed}")
        logger.info(f"{'='*60}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
