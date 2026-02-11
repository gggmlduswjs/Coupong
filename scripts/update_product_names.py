"""
상품명 최적화 일괄 업데이트 스크립트
====================================
쿠팡 검색은 sellerProductName 기준으로 매칭.
기존 제목은 절대 건드리지 않고, 뒤에 누락된 메타데이터 토큰만 추가 (append-only).

전략:
  - 교재류: 연도 → 학년 → 출판사 → 과목 → 학기
  - 자격증: 약어 → 등급+유형 → 연도 → 출판사
  - 일반도서: 저자 → 출판사 → 연도

사용법:
  # 드라이런 (변경 없이 미리보기)
  python scripts/update_product_names.py --dry-run --limit 20

  # 특정 계정만
  python scripts/update_product_names.py --account 007-book --limit 5

  # 전체 실행
  python scripts/update_product_names.py
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
from app.models.account import Account
from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
from uploaders.coupang_api_uploader import _dedupe_attributes
from scripts.update_search_tags import extract_components

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ─── 상품명에 넣으면 안 되는 브랜드/플레이스홀더 ────────────────
EXCLUDED_BRANDS = {
    "자체브랜드", "상세설명참조", "해당없음", "없음", "기타", "-",
}


# ─── 도서 유형 분류 ─────────────────────────────────────────────

TEXTBOOK_KEYWORDS = [
    "수학", "국어", "영어", "과학", "사회", "문제집", "참고서",
    "교과서", "기출", "모의고사", "워크북", "수능", "EBS",
    "내신", "개념", "유형", "총정리", "실전",
    "완자", "쎈", "오투", "한끝", "RPM", "마플", "개념원리",
    "풍산자", "올림포스", "블랙라벨", "라이트쎈", "개념쎈",
    "마더텅", "수능특강", "수능완성", "우공비", "자이스토리",
    "빠작", "디딤돌", "소마셈", "큐브수학",
    "초등", "중학", "중등", "고등", "고1", "고2", "고3",
    "중1", "중2", "중3", "초1", "초2", "초3", "초4", "초5", "초6",
    "1학기", "2학기", "학기",
]

CERT_KEYWORDS = [
    "자격증", "기사", "기능사", "산업기사",
    "컴퓨터활용", "정보처리", "워드프로세서", "한식조리", "양식조리",
    "요양보호사", "빅데이터분석", "네트워크관리", "사무자동화",
    "시나공", "ITQ", "GTQ", "DIAT",
    "필기", "실기",
]


def classify_book_type(product_name: str, category: str = "") -> str:
    """도서 유형 분류: textbook, cert, general"""
    text = (product_name + " " + category).lower()
    # 자격증 먼저 (더 구체적)
    for kw in CERT_KEYWORDS:
        if kw.lower() in text:
            return "cert"
    for kw in TEXTBOOK_KEYWORDS:
        if kw.lower() in text:
            return "textbook"
    return "general"


# ─── 토큰 생성 (유형별 우선순위) ─────────────────────────────────

def get_tokens_for_textbook(comp: Dict) -> List[str]:
    """교재류: 연도 → 학년 → 출판사 → 과목 → 학기"""
    tokens = []
    if comp.get("year"):
        tokens.append(comp["year"])
    if comp.get("grade_tag"):
        tokens.append(comp["grade_tag"])
    elif comp.get("grade_level"):
        tokens.append(comp["grade_level"])
    if comp.get("publisher"):
        tokens.append(comp["publisher"])
    if comp.get("subject"):
        tokens.append(comp["subject"])
    return tokens


def get_tokens_for_cert(comp: Dict) -> List[str]:
    """자격증: 약어 → 등급+유형 → 연도 → 출판사"""
    tokens = []
    if comp.get("cert_abbrevs"):
        tokens.extend(comp["cert_abbrevs"])
    if comp.get("cert_level") and comp.get("cert_type"):
        tokens.append(f"{comp['cert_level']} {comp['cert_type']}")
    elif comp.get("cert_level"):
        tokens.append(comp["cert_level"])
    elif comp.get("cert_type"):
        tokens.append(comp["cert_type"])
    if comp.get("year"):
        tokens.append(comp["year"])
    if comp.get("publisher"):
        tokens.append(comp["publisher"])
    return tokens


def get_tokens_for_general(comp: Dict) -> List[str]:
    """일반도서: 저자 → 출판사 → 연도"""
    tokens = []
    if comp.get("author"):
        tokens.append(comp["author"])
    if comp.get("publisher"):
        tokens.append(comp["publisher"])
    if comp.get("year"):
        tokens.append(comp["year"])
    return tokens


def build_optimized_name(
    current_name: str,
    book_type: str,
    comp: Dict,
    max_len: int = 100,
) -> str:
    """
    기존 이름 뒤에 누락 토큰만 append (100자 제한)
    이미 이름에 포함된 토큰은 skip (중복 방지)
    """
    if book_type == "textbook":
        tokens = get_tokens_for_textbook(comp)
    elif book_type == "cert":
        tokens = get_tokens_for_cert(comp)
    else:
        tokens = get_tokens_for_general(comp)

    base = current_name.strip()
    added = []

    for token in tokens:
        if not token or not token.strip():
            continue
        token = token.strip()
        # 자체브랜드/플레이스홀더 제외
        if token in EXCLUDED_BRANDS:
            continue
        # 중복 체크: 토큰이 이미 base에 있으면 skip
        if token in base:
            continue
        candidate = base + " " + token
        if len(candidate) <= max_len:
            base = candidate
            added.append(token)
        else:
            break

    return base, added


# ─── WING API 상품명 업데이트 ────────────────────────────────────

def update_product_name(
    client: CoupangWingClient,
    seller_product_id: str,
    new_seller_name: str,
    new_display_name: str,
    raw_json: str,
) -> Tuple[bool, str]:
    """
    기존 상품의 sellerProductName + displayProductName + itemName 업데이트
    PUT /seller-products (ID는 body에)
    """
    try:
        data = json.loads(raw_json)
        product = data.get("data", data)
        items = product.get("items", [])
        if not items:
            return False, "items가 비어있음"

        # 현재 이름과 동일하면 스킵
        current_name = product.get("sellerProductName", "")
        if current_name == new_seller_name:
            return True, "이름 동일 (스킵)"

        pid = int(seller_product_id)
        payload = {
            "sellerProductId": pid,
            "displayCategoryCode": product["displayCategoryCode"],
            "sellerProductName": new_seller_name,
            "vendorId": product["vendorId"],
            "saleStartedAt": product.get("saleStartedAt", ""),
            "saleEndedAt": product.get("saleEndedAt", "2099-12-31T00:00:00"),
            "displayProductName": new_display_name,
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

        # items 구성 — itemName도 업데이트
        for item in items:
            item_name = new_seller_name[:150]  # itemName ≤ 150자
            item_payload = {
                "sellerProductItemId": item["sellerProductItemId"],
                "itemName": item_name,
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
                "attributes": _dedupe_attributes(item.get("attributes", [])),
                "contents": item.get("contents", []),
                "certifications": item.get("certifications", []),
            }
            payload["items"].append(item_payload)

        base_path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
        result = client._request("PUT", base_path, data=payload)
        code = result.get("code", "")
        if code == "SUCCESS":
            return True, "성공"

        msg = str(result.get("message", result))
        # 쿼터 초과 감지
        if "초과" in msg and "구매옵션" in msg:
            return False, "QUOTA_EXCEEDED"
        return False, f"응답: {msg[:100]}"

    except CoupangWingError as e:
        err_msg = str(e)
        if "초과" in err_msg and "구매옵션" in err_msg:
            return False, "QUOTA_EXCEEDED"
        return False, f"API 오류: {e}"
    except Exception as e:
        return False, f"예외: {e}"


def build_display_name(publisher: str, seller_name: str, max_len: int = 100) -> str:
    """displayProductName = 출판사 + sellerProductName (≤100자)"""
    if not publisher or publisher in seller_name or publisher in EXCLUDED_BRANDS:
        return seller_name[:max_len]
    candidate = f"{publisher} {seller_name}"
    return candidate[:max_len]


# ─── 메인 ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="상품명 최적화 일괄 업데이트")
    parser.add_argument("--account", type=str, help="특정 계정만 (예: 007-book)")
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 상품 수 (0=전체)")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 미리보기")
    parser.add_argument("--delay", type=float, default=0.15, help="API 호출 간 대기 (초)")
    parser.add_argument("--skip-long", type=int, default=80, help="이미 N자 이상인 이름 스킵")
    args = parser.parse_args()

    db = SessionLocal()

    try:
        # 대상 계정 조회
        account_query = db.query(Account).filter(Account.wing_api_enabled == True)
        if args.account:
            account_query = account_query.filter(Account.account_name == args.account)
        accounts = account_query.all()

        if not accounts:
            logger.error("대상 계정 없음")
            return

        logger.info(f"대상 계정: {[a.account_name for a in accounts]}")

        total_updated = 0
        total_skipped = 0
        total_failed = 0
        total_same = 0
        total_quota = 0

        for account in accounts:
            logger.info(f"\n{'='*60}")
            logger.info(f"계정: {account.account_name} (vendor_id={account.vendor_id})")
            logger.info(f"{'='*60}")

            # 해당 계정의 listing 조회 (raw_json 있는 것만, bundle 제외)
            query = db.query(Listing).filter(
                Listing.account_id == account.id,
                Listing.coupang_product_id != None,
                Listing.raw_json != None,
                Listing.bundle_id.is_(None),  # bundle 제외 (product_type 삭제됨)
            )
            listings = query.all()
            logger.info(f"  총 {len(listings)}개 listing (bundle 제외)")

            # seller_product_id 기준 중복 제거
            seen_pids = set()
            unique_listings = []
            for l in listings:
                try:
                    raw = json.loads(l.raw_json)
                    prod = raw.get("data", raw)
                    pid = str(prod.get("sellerProductId", ""))
                    if pid and pid not in seen_pids:
                        seen_pids.add(pid)
                        unique_listings.append(l)
                except Exception:
                    continue

            logger.info(f"  고유 상품: {len(unique_listings)}개")

            # WING API 클라이언트
            client = None
            if not args.dry_run:
                client = CoupangWingClient(
                    vendor_id=account.vendor_id,
                    access_key=account.wing_access_key,
                    secret_key=account.wing_secret_key,
                )

            processed = 0
            account_updated = 0
            quota_hit = False

            for listing in unique_listings:
                if args.limit and processed >= args.limit:
                    break
                if quota_hit:
                    break

                # raw_json 파싱
                raw_data = json.loads(listing.raw_json)
                prod_data = raw_data.get("data", raw_data)
                items = prod_data.get("items", [])
                if not items:
                    total_skipped += 1
                    continue

                current_name = prod_data.get("sellerProductName", "")
                if not current_name:
                    total_skipped += 1
                    continue

                # 이미 충분히 긴 이름 스킵
                if len(current_name) >= args.skip_long:
                    total_skipped += 1
                    continue

                # Book 데이터 조회
                book = None
                if listing.isbn:
                    book = db.query(Book).filter(Book.isbn == listing.isbn).first()

                pub_name = ""
                auth_name = ""
                cat_name = ""
                if book:
                    pub_name = book.publisher.name if book.publisher else ""
                    auth_name = ""  # author 컬럼 삭제됨
                    cat_name = ""  # category 컬럼 삭제됨
                elif listing.brand:
                    pub_name = listing.brand

                # 도서 유형 분류
                book_type = classify_book_type(current_name, cat_name)

                # 구성요소 추출
                comp = extract_components(current_name, pub_name, auth_name, cat_name)

                # 최적화된 이름 빌드
                new_seller_name, added_tokens = build_optimized_name(
                    current_name, book_type, comp, max_len=100,
                )

                # 추가할 토큰이 없으면 스킵
                if not added_tokens:
                    total_same += 1
                    continue

                # displayProductName 빌드
                new_display_name = build_display_name(pub_name, new_seller_name, max_len=100)

                processed += 1

                if args.dry_run:
                    type_label = {"textbook": "교재", "cert": "자격증", "general": "일반"}[book_type]
                    logger.info(f"\n  [{processed}] [{type_label}] {current_name}")
                    logger.info(f"    → {new_seller_name}")
                    logger.info(f"    추가: {added_tokens}")
                    logger.info(f"    표시명: {new_display_name}")
                    logger.info(f"    길이: {len(current_name)} → {len(new_seller_name)}자")
                    total_updated += 1
                else:
                    seller_pid = listing.coupang_product_id
                    success, msg = update_product_name(
                        client,
                        seller_pid,
                        new_seller_name,
                        new_display_name,
                        listing.raw_json,
                    )

                    if success:
                        if "스킵" in msg:
                            total_same += 1
                        else:
                            total_updated += 1
                            account_updated += 1
                            logger.info(
                                f"  [{processed}] OK: {current_name[:30]} "
                                f"→ +{added_tokens}"
                            )
                    else:
                        if msg == "QUOTA_EXCEEDED":
                            logger.warning(f"  ⚠ 쿼터 초과! 이 계정 중단.")
                            total_quota += 1
                            quota_hit = True
                        else:
                            total_failed += 1
                            logger.warning(
                                f"  [{processed}] FAIL: {current_name[:30]} → {msg}"
                            )

                    time.sleep(args.delay)

            logger.info(f"  → {account.account_name}: {account_updated}건 업데이트")

        # 결과 요약
        logger.info(f"\n{'='*60}")
        logger.info(f"상품명 최적화 완료!")
        logger.info(f"  업데이트: {total_updated}")
        logger.info(f"  동일(스킵): {total_same}")
        logger.info(f"  스킵(긴이름/기타): {total_skipped}")
        logger.info(f"  실패: {total_failed}")
        logger.info(f"  쿼터 초과 계정: {total_quota}")
        logger.info(f"{'='*60}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
