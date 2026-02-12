"""
WING API 상품 등록 테스트
=========================
DB에서 상품 1개를 골라 WING API로 등록 테스트

사용법:
    python scripts/test_api_upload.py                     # 007-book 계정, DB 첫 번째 상품
    python scripts/test_api_upload.py --account 007-bm    # 특정 계정
    python scripts/test_api_upload.py --isbn 9788961336512  # 특정 ISBN
    python scripts/test_api_upload.py --dry-run            # 페이로드만 출력 (등록 안 함)
"""
import sys
import os
import json
import argparse
import logging
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal, init_db
from app.models.product import Product
from app.models.book import Book
from app.models.account import Account
from app.api.coupang_wing_client import CoupangWingClient
from uploaders.coupang_api_uploader import CoupangAPIUploader

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def get_test_product(db, isbn=None):
    """테스트용 상품 1개 조회"""
    query = db.query(Product).join(Book).filter(
        Product.status == 'ready',
        Product.can_upload_single == True,
    )

    if isbn:
        query = query.filter(Product.isbn == isbn)

    product = query.first()
    if not product:
        return None

    book = product.book

    # API 업로더가 사용하는 딕셔너리 형식으로 변환
    return {
        "product_name": book.title,
        "original_price": product.list_price,
        "sale_price": product.sale_price,
        "isbn": product.isbn,
        "publisher": book.publisher.name if book.publisher else "",
        "shipping_policy": product.shipping_policy,
        "net_margin": product.net_margin,
    }


def run_test(account_name="007-book", isbn=None, dry_run=False):
    """테스트 실행"""
    print("\n" + "=" * 60)
    print("  WING API 상품 등록 테스트")
    print("=" * 60)

    init_db()
    db = SessionLocal()

    try:
        # 계정 조회
        account = db.query(Account).filter(
            Account.account_name == account_name,
            Account.wing_api_enabled == True,
        ).first()

        if not account:
            print(f"\n  [FAIL] 계정 '{account_name}' 없음 또는 WING API 비활성")
            return

        if not account.outbound_shipping_code or not account.return_center_code:
            print(f"\n  [FAIL] 출고지/반품지 코드 미설정")
            print(f"  먼저 실행: python scripts/setup_shipping_places.py")
            return

        print(f"\n  계정: {account.account_name} (vendor_id={account.vendor_id})")
        print(f"  출고지: {account.outbound_shipping_code}")
        print(f"  반품지: {account.return_center_code}")

        # 상품 조회
        product_data = get_test_product(db, isbn)
        if not product_data:
            print(f"\n  [FAIL] 등록 가능한 상품 없음")
            return

        print(f"\n  상품: {product_data['product_name']}")
        print(f"  ISBN: {product_data['isbn']}")
        print(f"  정가: {product_data['original_price']:,}원")
        print(f"  판매가: {product_data['sale_price']:,}원")
        print(f"  마진: {product_data['net_margin']:,}원")
        print(f"  출판사: {product_data['publisher']}")
        print(f"  배송: {product_data['shipping_policy']}")

        # WING 클라이언트 + 업로더 생성
        client = CoupangWingClient(
            vendor_id=account.vendor_id,
            access_key=account.wing_access_key,
            secret_key=account.wing_secret_key,
        )
        uploader = CoupangAPIUploader(client, vendor_user_id=account.account_name)

        # 페이로드 생성
        print(f"\n--- 페이로드 생성 ---")
        payload = uploader.build_product_payload(
            product_data,
            account.outbound_shipping_code,
            account.return_center_code,
        )
        print(f"  카테고리: {payload['displayCategoryCode']}")
        print(f"  배송방식: {payload['deliveryChargeType']}")

        if dry_run:
            print(f"\n--- [DRY-RUN] 페이로드 내용 ---")
            # 긴 내용 축약
            display_payload = {k: v for k, v in payload.items() if k != "items"}
            print(json.dumps(display_payload, ensure_ascii=False, indent=2))
            print(f"\n  items[0] 주요 필드:")
            item = payload["items"][0]
            for key in ["itemName", "originalPrice", "salePrice", "barcode", "offerCondition", "taxType"]:
                print(f"    {key}: {item.get(key)}")
            print(f"    images: {len(item.get('images', []))}개")
            print(f"    searchTags: {item.get('searchTags', [])}")
            print(f"\n  [DRY-RUN] 등록하지 않음")
            return payload

        # 실제 등록
        print(f"\n--- 상품 등록 시도 ---")
        result = uploader.upload_product(
            product_data,
            account.outbound_shipping_code,
            account.return_center_code,
        )

        if result["success"]:
            print(f"\n  [OK] 등록 성공!")
            print(f"  sellerProductId: {result['seller_product_id']}")
            print(f"\n  쿠팡 판매자센터에서 확인하세요.")
        else:
            print(f"\n  [FAIL] 등록 실패")
            print(f"  오류: {result['message']}")

        print("=" * 60)
        return result

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="WING API 상품 등록 테스트")
    parser.add_argument(
        "--account", default="007-book",
        help="등록할 계정 (기본: 007-book)"
    )
    parser.add_argument(
        "--isbn",
        help="특정 ISBN 상품 등록 (기본: DB 첫 번째 상품)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="페이로드만 출력, 실제 등록 안 함"
    )

    args = parser.parse_args()

    run_test(
        account_name=args.account,
        isbn=args.isbn,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
