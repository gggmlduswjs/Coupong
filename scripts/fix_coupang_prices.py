"""
쿠팡 등록 상품 가격 수정 스크립트
==================================
배송비수정_상품목록.txt의 384개 상품 가격을 WING API로 수정

사용법:
    python scripts/fix_coupang_prices.py --dry-run  # 미리보기
    python scripts/fix_coupang_prices.py --apply    # 실제 적용
"""
import sys
import re
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from dotenv import load_dotenv
from app.database import SessionLocal
from app.models import Listing, Book, Account
from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
from app.constants import WING_ACCOUNT_ENV_MAP

load_dotenv()


def load_target_products(filepath: str) -> dict:
    """파일에서 계정별 상품 ID 추출"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 계정별 분류
    current_account = None
    by_account = {}

    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            current_account = line[1:-1]
            by_account[current_account] = []
        elif current_account:
            ids = re.findall(r'\b(160\d{8})\b', line)
            by_account[current_account].extend(ids)

    return by_account


def get_wing_client(account_name: str) -> CoupangWingClient:
    """계정별 WING API 클라이언트 생성"""
    env_prefix = WING_ACCOUNT_ENV_MAP.get(account_name)
    if not env_prefix:
        raise ValueError(f"Unknown account: {account_name}")

    vendor_id = os.getenv(f"{env_prefix}_VENDOR_ID")
    access_key = os.getenv(f"{env_prefix}_ACCESS_KEY")
    secret_key = os.getenv(f"{env_prefix}_SECRET_KEY")

    if not all([vendor_id, access_key, secret_key]):
        raise ValueError(f"Missing credentials for {account_name}")

    return CoupangWingClient(vendor_id, access_key, secret_key)


def fix_prices(dry_run: bool = True):
    """가격 수정 실행"""
    filepath = Path(__file__).parent.parent / "배송비수정_상품목록.txt"
    by_account = load_target_products(str(filepath))

    print("=" * 60)
    print("쿠팡 상품 가격 수정")
    print("=" * 60)

    total_products = sum(len(ids) for ids in by_account.values())
    print(f"대상 상품: {total_products}개")
    print(f"모드: {'DRY RUN (미리보기)' if dry_run else 'APPLY (실제 적용)'}")
    print()

    db = SessionLocal()
    total_success = 0
    total_fail = 0
    total_skip = 0

    for account_name, product_ids in by_account.items():
        if not product_ids:
            continue

        print(f"\n[{account_name}] {len(product_ids)}개 상품")
        print("-" * 50)

        try:
            client = get_wing_client(account_name)
        except ValueError as e:
            print(f"  ERROR: {e}")
            total_skip += len(product_ids)
            continue

        for i, pid in enumerate(product_ids, 1):
            listing = db.query(Listing).filter(Listing.coupang_product_id == pid).first()

            if not listing:
                print(f"  [{i}] {pid} - DB에 없음 (SKIP)")
                total_skip += 1
                continue

            if not listing.vendor_item_id or listing.vendor_item_id == "None":
                print(f"  [{i}] {pid} - vendor_item_id 없음 (SKIP)")
                total_skip += 1
                continue

            book = db.query(Book).filter(Book.isbn == listing.isbn).first()
            if not book:
                print(f"  [{i}] {pid} - Book 없음 (SKIP)")
                total_skip += 1
                continue

            # 올바른 가격 계산
            correct_price = int(book.list_price * 0.9)
            current_price = listing.sale_price or 0
            stock = listing.stock_quantity or 10

            if current_price == correct_price:
                print(f"  [{i}] {pid} - 가격 정상 {correct_price:,}원 (SKIP)")
                total_skip += 1
                continue

            diff = correct_price - current_price
            name = (listing.product_name or book.title or '')[:30]
            print(f"  [{i}] {pid} | {current_price:>7,} -> {correct_price:>7,} (+{diff:,}) | {name}")

            if dry_run:
                total_success += 1
                continue

            # API 호출
            try:
                result = client.update_price(
                    vendor_item_id=int(listing.vendor_item_id),
                    new_price=correct_price
                )

                # 응답 확인
                code = result.get("code", "")
                if code == "ERROR":
                    msg = result.get("message", "알 수 없는 오류")
                    print(f"      -> FAIL: {msg[:50]}")
                    total_fail += 1
                    continue

                # 성공 시 DB 업데이트 (coupang_sale_price 삭제됨, sale_price만 업데이트)
                listing.sale_price = correct_price
                db.commit()

                print(f"      -> OK")
                total_success += 1

                # Rate limit
                time.sleep(0.15)

            except CoupangWingError as e:
                print(f"      -> FAIL: {e}")
                total_fail += 1

    db.close()

    print()
    print("=" * 60)
    print("결과 요약")
    print("=" * 60)
    print(f"성공: {total_success}")
    print(f"실패: {total_fail}")
    print(f"스킵: {total_skip}")

    if dry_run:
        print()
        print("DRY RUN 완료. 실제 적용하려면:")
        print("  python scripts/fix_coupang_prices.py --apply")


def main():
    parser = argparse.ArgumentParser(description="쿠팡 상품 가격 수정")
    parser.add_argument("--dry-run", action="store_true", help="미리보기만")
    parser.add_argument("--apply", action="store_true", help="실제 적용")
    args = parser.parse_args()

    if not args.apply:
        args.dry_run = True

    fix_prices(dry_run=not args.apply)


if __name__ == "__main__":
    main()
