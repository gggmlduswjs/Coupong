"""
다른 계정에서 ISBN 복사 (PostgreSQL 전용)

같은 상품을 판매하는 다른 계정의 ISBN을 복사합니다.
- 상품명 기반 매칭 (정규화 후 비교)
- Jaccard 유사도 기반 (기본 80% 이상)
"""
import sys
import io
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

# UTF-8 출력 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from app.database import get_db


def normalize_product_name(name: str) -> str:
    """상품명 정규화 (매칭용)"""
    if not name:
        return ""

    normalized = name.lower()

    patterns_to_remove = [
        r'\(.*?\)', r'\[.*?\]',
        r'사은품', r'선물', r'증정', r'무료배송',
        r'\+', r'&', r'세트',
    ]

    for pattern in patterns_to_remove:
        normalized = re.sub(pattern, ' ', normalized)

    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip()


def calculate_similarity(name1: str, name2: str) -> float:
    """두 상품명의 Jaccard 유사도 (0.0 ~ 1.0)"""
    if not name1 or not name2:
        return 0.0

    words1 = set(normalize_product_name(name1).split())
    words2 = set(normalize_product_name(name2).split())

    if not words1 or not words2:
        return 0.0

    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0


def copy_isbn_from_other_accounts(
    dry_run: bool = False,
    limit: int = None,
    account_id: int = None,
    min_similarity: float = 0.8
):
    """다른 계정에서 ISBN 복사 (PostgreSQL 전용)"""
    db = next(get_db())

    print("=" * 80)
    print("다른 계정에서 ISBN 복사")
    print("=" * 80)
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모드: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"최소 유사도: {min_similarity * 100:.0f}%")
    if limit:
        print(f"제한: {limit}개")
    if account_id:
        print(f"계정: ID {account_id}")
    print()

    # ISBN 있는 상품 전부 메모리에 로드 (비교용)
    source_result = db.execute(text("""
        SELECT product_name, isbn, account_id
        FROM listings
        WHERE isbn IS NOT NULL AND isbn != ''
          AND product_name IS NOT NULL
    """))
    source_listings = source_result.fetchall()
    print(f"참조 소스: {len(source_listings):,}개 (ISBN 보유)")

    # ISBN 없는 상품 조회
    query = """
        SELECT id, account_id, product_name
        FROM listings
        WHERE (isbn IS NULL OR isbn = '')
          AND product_name IS NOT NULL
          AND product_name != ''
    """
    params = {}
    if account_id:
        query += " AND account_id = :account_id"
        params["account_id"] = account_id

    query += " ORDER BY id"
    if limit:
        query += f" LIMIT {limit}"

    result = db.execute(text(query), params)
    candidates = result.fetchall()

    print(f"대상: {len(candidates):,}개")
    print()

    stats = {
        'total': len(candidates),
        'success': 0,
        'failed': 0,
        'by_similarity': {
            '80-85%': 0, '85-90%': 0, '90-95%': 0, '95-100%': 0
        }
    }

    if stats['total'] == 0:
        print("ISBN이 없는 레코드가 없습니다.")
        return stats

    updated_listings = []

    for idx, row in enumerate(candidates, 1):
        listing_id = row[0]
        acc_id = row[1]
        product_name = row[2]

        # 다른 계정에서 유사한 상품 찾기
        best_isbn = None
        best_similarity = 0.0
        best_source_name = None

        for source_name, source_isbn, source_acc_id in source_listings:
            if source_acc_id == acc_id:
                continue

            similarity = calculate_similarity(product_name, source_name)
            if similarity > best_similarity and similarity >= min_similarity:
                best_similarity = similarity
                best_isbn = source_isbn
                best_source_name = source_name

        if best_isbn:
            if best_similarity >= 0.95:
                stats['by_similarity']['95-100%'] += 1
            elif best_similarity >= 0.90:
                stats['by_similarity']['90-95%'] += 1
            elif best_similarity >= 0.85:
                stats['by_similarity']['85-90%'] += 1
            else:
                stats['by_similarity']['80-85%'] += 1

            stats['success'] += 1
            updated_listings.append((listing_id, best_isbn, product_name, best_source_name, best_similarity))

            if stats['success'] <= 10:
                print(f"  [{stats['success']}] {product_name[:55]}")
                print(f"   -> ISBN: {best_isbn} | 유사도: {best_similarity*100:.1f}%")
                print(f"   <- 원본: {best_source_name[:55]}")
        else:
            stats['failed'] += 1

        if idx % 100 == 0:
            print(f"진행: {idx:,}/{len(candidates):,} ({idx/len(candidates)*100:.1f}%) - 성공: {stats['success']:,}")

    print()
    print("=" * 80)
    print("처리 결과")
    print("=" * 80)
    print(f"총 처리: {stats['total']:,}개")
    print(f"성공: {stats['success']:,}개 ({stats['success']/stats['total']*100:.1f}%)")
    print(f"실패: {stats['failed']:,}개")
    print()

    if stats['success'] > 0:
        print("유사도 분포:")
        for range_name, count in sorted(stats['by_similarity'].items(), reverse=True):
            if count > 0:
                print(f"   {range_name}: {count:4d}개 ({count/stats['success']*100:.1f}%)")
        print()

    if not dry_run and updated_listings:
        print("업데이트 중...")
        update_count = 0

        for listing_id, isbn, _, _, _ in updated_listings:
            try:
                db.execute(
                    text("UPDATE listings SET isbn = :isbn WHERE id = :id"),
                    {"isbn": isbn, "id": listing_id}
                )
                update_count += 1

                if update_count % 100 == 0:
                    db.commit()
                    print(f"   체크포인트: {update_count:,}개")

            except Exception as e:
                print(f"  ID {listing_id} 실패: {e}")
                continue

        db.commit()
        print(f"완료: {update_count:,}개")
    else:
        print("DRY RUN")

    print()
    print(f"종료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='다른 계정에서 ISBN 복사')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--account', type=int)
    parser.add_argument('--similarity', type=float, default=0.8, help='최소 유사도 (0.0~1.0)')

    args = parser.parse_args()

    try:
        stats = copy_isbn_from_other_accounts(
            dry_run=args.dry_run,
            limit=args.limit,
            account_id=args.account,
            min_similarity=args.similarity
        )

        if stats['total'] > 0:
            print()
            print(f"성공률: {stats['success']/stats['total']*100:.1f}%")

    except Exception as e:
        print(f"오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
