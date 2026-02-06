"""
가격 복구 스크립트
==================
알라딘 priceSales(판매가)를 priceStandard(정가)로 오인하여 저장한 문제 수정

문제:
- 크롤러가 priceSales(이미 10% 할인된 판매가)를 정가로 저장
- Publisher.calculate_margin()이 다시 10% 할인 적용
- 결과: 실제 판매가가 정가의 81% (19% 손해)

해결:
- DB의 list_price를 역산하여 원래 정가로 복원
- list_price / 0.9 = 정가

사용법:
    python scripts/fix_prices.py --dry-run  # 미리보기
    python scripts/fix_prices.py --apply    # 실제 적용
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from app.database import SessionLocal
from app.models import Book, Product

def analyze_prices(db):
    """가격 패턴 분석"""
    books = db.query(Book).all()

    sales_pattern = []  # 9로 나눠떨어짐 (판매가)
    standard_pattern = []  # 10으로 나눠떨어지고 9로는 안 나눠짐 (정가)

    for b in books:
        if b.list_price % 10 == 0 and b.list_price % 9 != 0:
            standard_pattern.append(b)
        elif b.list_price % 9 == 0:
            sales_pattern.append(b)
        else:
            # 둘 다 아닌 경우는 수동 확인 필요
            sales_pattern.append(b)

    return sales_pattern, standard_pattern

def fix_book_prices(db, dry_run=True):
    """도서 가격 복구"""
    sales_pattern, standard_pattern = analyze_prices(db)

    print("=" * 60)
    print("가격 복구 분석")
    print("=" * 60)
    print(f"복구 필요 (판매가 패턴): {len(sales_pattern)}개")
    print(f"정상 (정가 패턴): {len(standard_pattern)}개")
    print()

    if not sales_pattern:
        print("복구할 데이터가 없습니다.")
        return

    # 샘플 출력
    print("=== 복구 예시 (상위 10개) ===")
    for book in sales_pattern[:10]:
        original_price = int(book.list_price / 0.9)
        # 100원 단위로 반올림 (정가는 보통 100원 단위)
        original_price = round(original_price / 100) * 100

        print(f"  {book.title[:35]:35s}")
        print(f"    현재: {book.list_price:>7,}원 → 복구: {original_price:>7,}원")

    if dry_run:
        print()
        print("=== DRY RUN 모드 ===")
        print("실제 변경 없이 미리보기만 수행했습니다.")
        print("적용하려면: python scripts/fix_prices.py --apply")
        return

    # 실제 적용
    print()
    print("=== 복구 적용 중... ===")

    updated = 0
    for book in sales_pattern:
        original_price = int(book.list_price / 0.9)
        original_price = round(original_price / 100) * 100

        book.list_price = original_price
        updated += 1

    db.commit()

    print(f"완료: {updated}개 도서 가격 복구됨")

    # Product 테이블도 업데이트 필요한지 확인
    products = db.query(Product).all()
    if products:
        print()
        print(f"=== Product 테이블 ({len(products)}개) ===")
        print("Product의 sale_price는 Book.list_price 기반으로 재계산 필요")
        print("run_pipeline.py의 analyze 단계를 다시 실행하세요.")

def main():
    parser = argparse.ArgumentParser(description="가격 복구 스크립트")
    parser.add_argument("--dry-run", action="store_true", help="미리보기만 (기본값)")
    parser.add_argument("--apply", action="store_true", help="실제 적용")
    args = parser.parse_args()

    if not args.apply:
        args.dry_run = True

    db = SessionLocal()
    try:
        fix_book_prices(db, dry_run=not args.apply)
    finally:
        db.close()

if __name__ == "__main__":
    main()
