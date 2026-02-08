"""
상품 속성 일괄 업데이트
=======================
"상세내용 참조"로 되어 있는 속성값을 실제 값으로 채워서 WING API PUT

대상 속성:
  - 사용연도: 제목에서 추출
  - 학기구분: 제목에서 추출
  - 출시년월: books.publish_date
  - 출판사: books.publisher_name
  - 저자: books.author
  - 발행언어: "한국어"
  - ISBN: books.isbn

사용법:
  python scripts/update_attributes.py --dry-run --limit 5    # 미리보기
  python scripts/update_attributes.py --account 007-book     # 특정 계정만
  python scripts/update_attributes.py                         # 전체 실행
"""
import argparse
import json
import logging
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.listing import Listing
from app.models.book import Book
from app.models.product import Product
from app.models.account import Account
from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
from uploaders.coupang_api_uploader import (
    _dedupe_attributes, _parse_subject, _parse_grade, _parse_semester,
    _parse_series_name,
)
from scripts.sync_coupang_products import create_wing_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

PLACEHOLDER = {"상세내용 참조", "상세설명 참조", ""}


def _extract_year(title: str) -> str:
    """제목에서 사용연도 추출 → '2026년도' 형식"""
    m = re.search(r'(202[4-9])', title or "")
    if m:
        return f"{m.group(1)}년도"
    return ""


def _extract_publish_month(publish_date) -> str:
    """출간일 → '2026.01' 형식"""
    if not publish_date:
        return ""
    s = str(publish_date)
    m = re.match(r'(\d{4})-(\d{2})', s)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return ""


def compute_fixes(attrs: List[Dict], title: str, book_data: dict) -> Tuple[List[Dict], List[str]]:
    """
    속성 리스트에서 '상세내용 참조'를 실제 값으로 대체.
    Returns: (new_attrs, changed_list)
    """
    # 현재 속성을 dict로
    attr_map = {}
    for a in attrs:
        atn = a.get("attributeTypeName", "")
        avn = a.get("attributeValueName", "")
        attr_map[atn] = avn

    changes = []

    # 사용연도
    if attr_map.get("사용연도", "") in PLACEHOLDER:
        val = _extract_year(title)
        if val:
            attr_map["사용연도"] = val
            changes.append(f"사용연도→{val}")

    # 학기구분
    if attr_map.get("학기구분", "") in PLACEHOLDER:
        val = _parse_semester(title)
        if val:
            attr_map["학기구분"] = val
            changes.append(f"학기구분→{val}")

    # 출시년월
    if attr_map.get("출시년월", "") in PLACEHOLDER:
        val = _extract_publish_month(book_data.get("publish_date"))
        if val:
            attr_map["출시년월"] = val
            changes.append(f"출시년월→{val}")

    # 출판사
    if attr_map.get("출판사", "") in PLACEHOLDER:
        val = book_data.get("publisher_name", "")
        if val:
            attr_map["출판사"] = val
            changes.append(f"출판사→{val}")

    # 저자
    if attr_map.get("저자", "") in PLACEHOLDER:
        val = book_data.get("author", "")
        if val:
            attr_map["저자"] = val
            changes.append(f"저자→{val}")

    # 발행언어
    if attr_map.get("발행언어", "") in PLACEHOLDER:
        attr_map["발행언어"] = "한국어"
        changes.append("발행언어→한국어")

    # ISBN
    if attr_map.get("ISBN", "") in PLACEHOLDER:
        val = book_data.get("isbn", "")
        if val:
            attr_map["ISBN"] = val
            changes.append(f"ISBN→{val}")

    # 학습과목 (이미 채워진 비율 높지만 혹시 빈 것)
    if attr_map.get("학습과목", "") in PLACEHOLDER:
        val = _parse_subject(title)
        if val:
            attr_map["학습과목"] = val
            changes.append(f"학습과목→{val}")

    # 사용학년/단계 (이미 93% 채워짐, 나머지)
    if attr_map.get("사용학년/단계", "") in PLACEHOLDER:
        val = _parse_grade(title)
        if val:
            # 쿠팡 옵션값 형식에 맞게 변환
            grade_map = {
                "초등": "초등학생", "중등": "중학생", "고등": "고등학생", "수능": "고등학생",
            }
            # "초등 3-1" → "초등3학년", "중등 2" → "중등2학년" 등
            m = re.match(r'(초등|중등|고등)\s*(\d)(?:-(\d))?', val)
            if m:
                school = m.group(1)
                g = m.group(2)
                attr_map["사용학년/단계"] = f"{school}{g}학년"
            elif val in grade_map:
                attr_map["사용학년/단계"] = grade_map[val]
            else:
                attr_map["사용학년/단계"] = val
            changes.append(f"사용학년→{attr_map['사용학년/단계']}")

    if not changes:
        return attrs, []

    # 새 속성 리스트 재구성
    new_attrs = []
    for a in attrs:
        atn = a.get("attributeTypeName", "")
        new_a = dict(a)
        if atn in attr_map:
            new_a["attributeValueName"] = attr_map[atn]
        new_attrs.append(new_a)

    return new_attrs, changes


def update_product_attributes(
    client: CoupangWingClient,
    seller_product_id: str,
    raw_json: str,
    new_attrs_by_item: Dict[int, List[Dict]],
) -> Tuple[bool, str]:
    """기존 상품의 attributes만 업데이트 (나머지 필드 보존)"""
    try:
        data = json.loads(raw_json)
        product = data.get("data", data)
        items = product.get("items", [])
        if not items:
            return False, "items 비어있음"

        pid = int(seller_product_id)
        payload = {
            "sellerProductId": pid,
            "displayCategoryCode": product["displayCategoryCode"],
            "sellerProductName": product["sellerProductName"],
            "vendorId": product["vendorId"],
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
            "items": [],
        }

        for item in items:
            item_id = item.get("sellerProductItemId", 0)
            attrs = new_attrs_by_item.get(item_id, item.get("attributes", []))

            item_payload = {
                "sellerProductItemId": item["sellerProductItemId"],
                "itemName": item["itemName"],
                "originalPrice": item["originalPrice"],
                "salePrice": item["salePrice"],
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
                "attributes": _dedupe_attributes(attrs),
                "contents": item.get("contents", []),
                "certifications": item.get("certifications", []),
            }
            payload["items"].append(item_payload)

        base_path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
        result = client._request("PUT", base_path, data=payload)
        code = result.get("code", "")
        if code == "SUCCESS":
            return True, "성공"
        return False, f"응답: {str(result)[:100]}"

    except CoupangWingError as e:
        return False, f"API 오류: {e}"
    except Exception as e:
        return False, f"예외: {e}"


def main():
    parser = argparse.ArgumentParser(description="상품 속성 일괄 업데이트")
    parser.add_argument("--account", type=str, help="특정 계정만")
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 상품 수 (0=전체)")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 미리보기")
    parser.add_argument("--delay", type=float, default=0.15, help="API 호출 간 대기 (초)")
    args = parser.parse_args()

    db = SessionLocal()

    try:
        acct_q = db.query(Account).filter(
            Account.is_active == True,
            Account.wing_api_enabled == True,
        )
        if args.account:
            acct_q = acct_q.filter(Account.account_name == args.account)
        accounts = acct_q.all()

        if not accounts:
            logger.error("WING API 활성 계정 없음")
            return

        total_success = 0
        total_skip = 0
        total_fail = 0

        for account in accounts:
            logger.info(f"\n{'='*50}")
            logger.info(f"계정: {account.account_name}")

            # raw_json 있는 활성 리스팅 (고유 seller_product_id 기준)
            q = db.query(Listing).filter(
                Listing.account_id == account.id,
                Listing.coupang_status == "active",
                Listing.raw_json.isnot(None),
            )
            if args.limit > 0:
                q = q.limit(args.limit)
            listings = q.all()

            if not listings:
                logger.info(f"  처리할 리스팅 없음")
                continue

            # seller_product_id 기준 그룹핑 (중복 방지)
            seen_pids = set()
            unique_listings = []
            for l in listings:
                raw = json.loads(l.raw_json)
                pid = str(raw.get("sellerProductId", ""))
                if pid and pid not in seen_pids:
                    seen_pids.add(pid)
                    unique_listings.append(l)

            logger.info(f"  고유 상품: {len(unique_listings)}개 (리스팅: {len(listings)}개)")

            if not args.dry_run:
                try:
                    client = create_wing_client(account)
                except ValueError as e:
                    logger.error(f"  API 클라이언트 생성 실패: {e}")
                    continue

            success = 0
            skip = 0
            fail = 0
            start = time.time()

            for i, listing in enumerate(unique_listings):
                raw_data = json.loads(listing.raw_json)
                product = raw_data.get("data", raw_data)
                items = product.get("items", [])
                if not items:
                    skip += 1
                    continue

                pid = str(product.get("sellerProductId", ""))
                title = product.get("sellerProductName", listing.product_name or "")

                # book 데이터 가져오기
                book_data = {}
                if listing.product_id:
                    prod = db.query(Product).get(listing.product_id)
                    if prod and prod.book_id:
                        book = db.query(Book).get(prod.book_id)
                        if book:
                            book_data = {
                                "isbn": book.isbn or "",
                                "author": book.author or "",
                                "publisher_name": book.publisher_name or "",
                                "publish_date": book.publish_date,
                            }

                # 각 item의 attributes 수정
                new_attrs_by_item = {}
                all_changes = []
                for item in items:
                    item_id = item.get("sellerProductItemId", 0)
                    attrs = item.get("attributes", [])
                    new_attrs, changes = compute_fixes(attrs, title, book_data)
                    if changes:
                        new_attrs_by_item[item_id] = new_attrs
                        all_changes.extend(changes)

                if not all_changes:
                    skip += 1
                    continue

                short = title[:40]
                change_str = ", ".join(all_changes[:5])
                if len(all_changes) > 5:
                    change_str += f" 외 {len(all_changes)-5}개"

                if args.dry_run:
                    logger.info(f"  [{i+1}] {short} → {change_str}")
                    success += 1
                else:
                    ok, msg = update_product_attributes(
                        client, pid, listing.raw_json, new_attrs_by_item
                    )
                    if ok:
                        success += 1
                        if (success % 50) == 0:
                            elapsed = time.time() - start
                            logger.info(f"  [{i+1}/{len(unique_listings)}] 성공 {success}, 스킵 {skip}, 실패 {fail} ({elapsed:.0f}초)")
                    else:
                        fail += 1
                        # 일일 쿼터 초과 시 다음 계정으로
                        if "초과" in msg and "구매옵션" in msg:
                            logger.warning(f"  일일 쿼터 초과 — 다음 계정으로 넘어갑니다 (성공 {success})")
                            break
                        logger.warning(f"  [{i+1}] 실패: {short} - {msg}")

                    time.sleep(args.delay)

            elapsed = time.time() - start
            logger.info(f"  {account.account_name} 완료: 성공 {success}, 스킵 {skip}, 실패 {fail} ({elapsed:.0f}초)")
            total_success += success
            total_skip += skip
            total_fail += fail

        logger.info(f"\n{'='*50}")
        logger.info(f"전체 완료: 성공 {total_success}, 스킵 {total_skip}, 실패 {total_fail}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
