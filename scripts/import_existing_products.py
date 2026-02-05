"""
기존 쿠팡 등록상품 CSV → DB import (중복 방지용)
================================================

사용법:
    1. 쿠팡 판매자센터(wing.coupang.com) 로그인
    2. 상품관리 > 등록상품 관리 > 전체 선택 > 엑셀 다운로드
    3. 이 스크립트로 import

    python scripts/import_existing_products.py --account 007-book --file "다운로드/상품목록.csv"
    python scripts/import_existing_products.py --account 007-ez --file "다운로드/상품목록_ez.csv"

    # 한번에 여러 계정
    python scripts/import_existing_products.py --batch

참고:
    쿠팡 상품목록 CSV에서 ISBN(업체상품코드 또는 바코드)을 추출하여
    listings 테이블에 기록합니다. 이후 파이프라인 실행 시
    해당 ISBN은 자동으로 건너뜁니다.
"""
import sys
import os
import csv
import argparse
import logging
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal, init_db
from app.models.account import Account
from app.models.listing import Listing
from auto_logger import task_context
from obsidian_logger import ObsidianLogger

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# 쿠팡 CSV에서 ISBN을 찾을 수 있는 컬럼명 후보
ISBN_COLUMN_CANDIDATES = [
    "업체상품코드",
    "바코드",
    "판매자상품코드",
    "상품코드",
    "ISBN",
    "isbn",
    "바코드번호",
]

# 쿠팡 CSV에서 상품명을 찾을 수 있는 컬럼명 후보
NAME_COLUMN_CANDIDATES = [
    "노출상품명",
    "등록상품명",
    "상품명",
]

# 쿠팡 CSV에서 판매가를 찾을 수 있는 컬럼명 후보
PRICE_COLUMN_CANDIDATES = [
    "판매가격",
    "판매가",
    "가격",
]


def find_column(header, candidates):
    """헤더에서 매칭되는 컬럼 인덱스 찾기"""
    for candidate in candidates:
        for i, col in enumerate(header):
            if candidate in col:
                return i
    return None


def parse_coupang_csv(filepath):
    """
    쿠팡 상품목록 CSV 파싱

    Returns:
        [{isbn, product_name, sale_price, coupang_product_id}, ...]
    """
    products = []

    # 인코딩 자동 감지 (쿠팡은 보통 cp949 또는 utf-8-sig)
    for encoding in ["utf-8-sig", "cp949", "euc-kr", "utf-8"]:
        try:
            with open(filepath, "r", encoding=encoding) as f:
                reader = csv.reader(f)
                header = next(reader)

                # 컬럼 인덱스 찾기
                isbn_idx = find_column(header, ISBN_COLUMN_CANDIDATES)
                name_idx = find_column(header, NAME_COLUMN_CANDIDATES)
                price_idx = find_column(header, PRICE_COLUMN_CANDIDATES)

                if isbn_idx is None:
                    logger.warning(f"ISBN 컬럼을 찾을 수 없습니다. 헤더: {header[:15]}")
                    # 모든 컬럼명 출력
                    for i, col in enumerate(header):
                        logger.info(f"  [{i}] {col}")
                    return []

                logger.info(f"인코딩: {encoding}")
                logger.info(f"ISBN 컬럼: [{isbn_idx}] {header[isbn_idx]}")
                if name_idx is not None:
                    logger.info(f"상품명 컬럼: [{name_idx}] {header[name_idx]}")
                if price_idx is not None:
                    logger.info(f"판매가 컬럼: [{price_idx}] {header[price_idx]}")

                for row in reader:
                    if len(row) <= isbn_idx:
                        continue

                    isbn = row[isbn_idx].strip()
                    if not isbn:
                        continue

                    # ISBN 형식 검증 (숫자 10~13자리 또는 K로 시작하는 알라딘 코드)
                    if not (isbn.isdigit() and 10 <= len(isbn) <= 13) and not isbn.startswith("K"):
                        continue

                    product = {
                        "isbn": isbn,
                        "product_name": row[name_idx].strip() if name_idx and len(row) > name_idx else "",
                        "sale_price": 0,
                    }

                    if price_idx and len(row) > price_idx:
                        try:
                            product["sale_price"] = int(row[price_idx].replace(",", "").strip())
                        except (ValueError, AttributeError):
                            pass

                    products.append(product)

            break  # 성공하면 루프 종료

        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.error(f"CSV 파싱 오류 ({encoding}): {e}")
            continue

    return products


def import_to_db(account_name, products):
    """
    기존 상품을 listings 테이블에 import

    Args:
        account_name: 쿠팡 계정명
        products: parse_coupang_csv 결과
    """
    db = SessionLocal()

    try:
        # 계정 조회
        account = db.query(Account).filter(
            Account.account_name == account_name
        ).first()

        if not account:
            logger.error(f"계정을 찾을 수 없습니다: {account_name}")
            logger.info("등록된 계정 목록:")
            for acc in db.query(Account).all():
                logger.info(f"  - {acc.account_name}")
            return 0

        imported = 0
        skipped = 0

        for product in products:
            isbn = product["isbn"]

            # 이미 listings에 있는지 확인
            existing = db.query(Listing).filter(
                Listing.account_id == account.id,
                Listing.isbn == isbn
            ).first()

            if existing:
                skipped += 1
                continue

            # Listing 생성 (기존 쿠팡 등록 상품)
            listing = Listing(
                account_id=account.id,
                product_type="single",
                isbn=isbn,
                sale_price=product.get("sale_price", 0),
                shipping_policy="unknown",  # 기존 상품은 정책 모름
                upload_method="existing",   # 기존 등록 표시
                coupang_status="active",    # 이미 활성 상태
                uploaded_at=datetime.utcnow(),
            )
            db.add(listing)
            imported += 1

        db.commit()

        logger.info(f"\n{account_name} import 완료:")
        logger.info(f"  신규 등록: {imported}개")
        logger.info(f"  이미 존재: {skipped}개")
        logger.info(f"  총 listings: {db.query(Listing).filter(Listing.account_id == account.id).count()}개")

        return imported

    except Exception as e:
        logger.error(f"DB import 오류: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def import_single(account_name, filepath):
    """단일 계정 import"""
    filepath = Path(filepath)

    if not filepath.exists():
        logger.error(f"파일을 찾을 수 없습니다: {filepath}")
        return

    obs = ObsidianLogger()

    print(f"\n{'='*60}")
    print(f"  기존 상품 import: {account_name}")
    print(f"  파일: {filepath}")
    print(f"{'='*60}")

    with task_context("기존 상품 import", f"{account_name} 계정, 파일: {filepath.name}"):
        # CSV 파싱
        products = parse_coupang_csv(filepath)

        if not products:
            logger.warning("파싱된 상품이 없습니다.")
            return

        logger.info(f"CSV에서 {len(products)}개 상품 발견")

        # 미리보기
        print(f"\n처음 5개 상품:")
        for i, p in enumerate(products[:5], 1):
            name = p['product_name'][:40] if p['product_name'] else "(상품명 없음)"
            print(f"  {i}. {p['isbn']} | {name} | {p['sale_price']:,}원")

        if len(products) > 5:
            print(f"  ... 외 {len(products) - 5}개")

        # DB import
        imported = import_to_db(account_name, products)

        obs.log_to_daily(
            f"**{account_name}** 기존 상품 import\n- CSV: {filepath.name}\n- 파싱: {len(products)}개\n- 신규 등록: {imported}개",
            f"기존 상품 import: {account_name}"
        )

        print(f"\nimport 완료: {imported}개 신규 등록")


def import_batch():
    """대화형 일괄 import"""
    print("\n" + "=" * 60)
    print("  기존 쿠팡 상품 일괄 import")
    print("=" * 60)

    db = SessionLocal()
    accounts = db.query(Account).filter(Account.is_active == True).all()
    db.close()

    if not accounts:
        print("등록된 계정이 없습니다. 먼저 파이프라인을 실행하세요.")
        return

    print("\n등록된 계정:")
    for i, acc in enumerate(accounts, 1):
        print(f"  {i}. {acc.account_name}")

    print(f"\n각 계정별로 쿠팡에서 다운로드한 CSV 파일 경로를 입력하세요.")
    print(f"(건너뛰려면 Enter)")

    for acc in accounts:
        filepath = input(f"\n{acc.account_name} CSV 경로: ").strip()

        if not filepath:
            print(f"  → {acc.account_name} 건너뜀")
            continue

        filepath = Path(filepath)
        if not filepath.exists():
            print(f"  → 파일 없음: {filepath}")
            continue

        products = parse_coupang_csv(str(filepath))
        if products:
            imported = import_to_db(acc.account_name, products)
            print(f"  → {imported}개 등록 완료")
        else:
            print(f"  → 파싱된 상품 없음")

    # 최종 현황
    db = SessionLocal()
    print(f"\n{'='*60}")
    print(f"  import 완료 현황")
    print(f"{'='*60}")

    for acc in accounts:
        total = db.query(Listing).filter(Listing.account_id == acc.id).count()
        existing = db.query(Listing).filter(
            Listing.account_id == acc.id,
            Listing.upload_method == "existing"
        ).count()
        print(f"  {acc.account_name:15s}: 총 {total}개 (기존 {existing}개)")

    db.close()


def show_status():
    """현재 중복 방지 현황 표시"""
    db = SessionLocal()

    print(f"\n{'='*60}")
    print(f"  중복 방지 현황")
    print(f"{'='*60}")

    accounts = db.query(Account).filter(Account.is_active == True).all()

    for acc in accounts:
        total = db.query(Listing).filter(Listing.account_id == acc.id).count()
        existing = db.query(Listing).filter(
            Listing.account_id == acc.id,
            Listing.upload_method == "existing"
        ).count()
        csv_count = db.query(Listing).filter(
            Listing.account_id == acc.id,
            Listing.upload_method == "csv"
        ).count()
        print(f"  {acc.account_name:15s}: 총 {total}개 (기존 import {existing}개 + CSV 생성 {csv_count}개)")

    # 전체 고유 ISBN 수
    from sqlalchemy import func
    unique_isbns = db.query(func.count(func.distinct(Listing.isbn))).scalar()
    print(f"\n  전체 고유 ISBN: {unique_isbns}개")

    db.close()


def main():
    parser = argparse.ArgumentParser(description="기존 쿠팡 등록상품 import (중복 방지)")

    parser.add_argument(
        "--account",
        help="계정명 (예: 007-book)"
    )
    parser.add_argument(
        "--file",
        help="쿠팡에서 다운로드한 CSV 파일 경로"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="대화형 일괄 import 모드"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="현재 중복 방지 현황 표시"
    )

    args = parser.parse_args()

    init_db()

    if args.status:
        show_status()
    elif args.batch:
        import_batch()
    elif args.account and args.file:
        import_single(args.account, args.file)
    else:
        # 인자 없으면 현황 표시
        show_status()
        print(f"\n사용법:")
        print(f"  # 단일 계정 import")
        print(f"  python scripts/import_existing_products.py --account 007-book --file \"상품목록.csv\"")
        print(f"")
        print(f"  # 대화형 일괄 import")
        print(f"  python scripts/import_existing_products.py --batch")
        print(f"")
        print(f"  # 현황 확인")
        print(f"  python scripts/import_existing_products.py --status")


if __name__ == "__main__":
    main()
