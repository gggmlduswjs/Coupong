"""
다른 계정에서 ISBN 복사

같은 상품을 판매하는 다른 계정의 ISBN을 복사합니다.
- 상품명 기반 매칭 (정규화 후 비교)
- 계정간 ISBN 공유 (UNIQUE constraint 허용)
- 높은 신뢰도 매칭만 수행
"""
import sys
import io
import re
import sqlite3
from datetime import datetime
from typing import Optional, List, Tuple

# UTF-8 출력 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def normalize_product_name(name: str) -> str:
    """
    상품명 정규화 (매칭용)

    - 소문자 변환
    - 괄호/사은품/선물 등 제거
    - 공백 정리
    """
    if not name:
        return ""

    # 소문자
    normalized = name.lower()

    # 제거할 패턴
    patterns_to_remove = [
        r'\(.*?\)',  # 괄호
        r'\[.*?\]',  # 대괄호
        r'사은품',
        r'선물',
        r'증정',
        r'무료배송',
        r'\+',  # + 기호
        r'&',   # & 기호
        r'세트',
    ]

    for pattern in patterns_to_remove:
        normalized = re.sub(pattern, ' ', normalized)

    # 연속 공백 → 단일 공백
    normalized = re.sub(r'\s+', ' ', normalized)

    return normalized.strip()


def calculate_similarity(name1: str, name2: str) -> float:
    """
    두 상품명의 유사도 계산 (0.0 ~ 1.0)

    간단한 단어 집합 기반 Jaccard 유사도
    """
    if not name1 or not name2:
        return 0.0

    # 정규화
    norm1 = normalize_product_name(name1)
    norm2 = normalize_product_name(name2)

    # 단어 집합
    words1 = set(norm1.split())
    words2 = set(norm2.split())

    if not words1 or not words2:
        return 0.0

    # Jaccard 유사도
    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0


def find_isbn_from_other_accounts(
    product_name: str,
    account_id: int,
    conn,
    min_similarity: float = 0.7
) -> Optional[str]:
    """
    다른 계정에서 유사한 상품의 ISBN 찾기

    Args:
        product_name: 검색할 상품명
        account_id: 현재 계정 ID
        conn: DB 연결
        min_similarity: 최소 유사도 (0.7 = 70%)

    Returns:
        ISBN 또는 None
    """
    cursor = conn.cursor()

    # 다른 계정의 ISBN이 있는 상품들 조회
    cursor.execute("""
        SELECT product_name, isbn
        FROM listings
        WHERE account_id != ?
          AND isbn IS NOT NULL
          AND isbn != ''
          AND product_name IS NOT NULL
    """, (account_id,))

    candidates = cursor.fetchall()

    # 유사도 계산
    best_match = None
    best_similarity = 0.0

    for candidate_name, candidate_isbn in candidates:
        similarity = calculate_similarity(product_name, candidate_name)

        if similarity > best_similarity and similarity >= min_similarity:
            best_similarity = similarity
            best_match = (candidate_isbn, candidate_name, similarity)

    if best_match:
        return best_match[0]  # ISBN 반환

    return None


def copy_isbn_from_other_accounts(
    dry_run: bool = False,
    limit: int = None,
    db_path: str = 'coupang_auto_backup.db',
    account_id: int = None,
    min_similarity: float = 0.8
):
    """
    다른 계정에서 ISBN 복사

    Args:
        min_similarity: 최소 유사도 (기본값 0.8 = 80%)
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

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

    # ISBN 없는 상품 조회
    query = """
        SELECT id, account_id, product_name
        FROM listings
        WHERE (isbn IS NULL OR isbn = '')
        AND product_name IS NOT NULL
        AND product_name != ''
    """

    params = []
    if account_id:
        query += " AND account_id = ?"
        params.append(account_id)

    query += " ORDER BY id"

    if limit:
        query += f" LIMIT {limit}"

    cursor = conn.cursor()
    cursor.execute(query, params)
    candidates = cursor.fetchall()

    print(f"🔍 대상: {len(candidates):,}개")
    print()

    stats = {
        'total': len(candidates),
        'success': 0,
        'failed': 0,
        'duplicate': 0,
        'by_similarity': {
            '80-85%': 0,
            '85-90%': 0,
            '90-95%': 0,
            '95-100%': 0
        }
    }

    updated_listings = []

    for idx, row in enumerate(candidates, 1):
        listing_id = row[0]
        acc_id = row[1]
        product_name = row[2]

        # 다른 계정에서 ISBN 찾기
        isbn = find_isbn_from_other_accounts(product_name, acc_id, conn, min_similarity)

        if isbn:
            # 유사도 재계산 (출력용)
            cursor.execute("""
                SELECT product_name FROM listings
                WHERE isbn = ? AND account_id != ? LIMIT 1
            """, (isbn, acc_id))

            source_row = cursor.fetchone()
            if source_row:
                similarity = calculate_similarity(product_name, source_row[0])

                # 유사도 범위별 통계
                if similarity >= 0.95:
                    stats['by_similarity']['95-100%'] += 1
                elif similarity >= 0.90:
                    stats['by_similarity']['90-95%'] += 1
                elif similarity >= 0.85:
                    stats['by_similarity']['85-90%'] += 1
                else:
                    stats['by_similarity']['80-85%'] += 1

                stats['success'] += 1
                updated_listings.append((listing_id, isbn, product_name, source_row[0], similarity))

                if stats['success'] <= 10:
                    print(f"✓ [{stats['success']}] {product_name[:55]}")
                    print(f"   → ISBN: {isbn} | 유사도: {similarity*100:.1f}%")
                    print(f"   ← 원본: {source_row[0][:55]}")
        else:
            stats['failed'] += 1

        if idx % 100 == 0:
            print(f"진행: {idx:,}/{len(candidates):,} ({idx/len(candidates)*100:.1f}%) - 성공: {stats['success']:,}")

    print()
    print("=" * 80)
    print("처리 결과")
    print("=" * 80)
    print(f"총 처리: {stats['total']:,}개")
    print(f"✅ 성공: {stats['success']:,}개 ({stats['success']/stats['total']*100:.1f}%)")
    print(f"❌ 실패: {stats['failed']:,}개")
    print()

    if stats['success'] > 0:
        print("📊 유사도 분포:")
        for range_name, count in sorted(stats['by_similarity'].items(), reverse=True):
            if count > 0:
                print(f"   {range_name}: {count:4d}개 ({count/stats['success']*100:.1f}%)")
        print()

    if not dry_run and updated_listings:
        print("💾 업데이트 중...")

        update_count = 0
        duplicate_count = 0

        for listing_id, isbn, product_name, source_name, similarity in updated_listings:
            try:
                cursor = conn.cursor()

                cursor.execute("SELECT account_id FROM listings WHERE id = ?", (listing_id,))
                row = cursor.fetchone()
                if not row:
                    continue

                acc_id = row[0]

                # 중복 체크
                cursor.execute("""
                    SELECT COUNT(*) FROM listings
                    WHERE account_id = ? AND isbn = ? AND id != ?
                """, (acc_id, isbn, listing_id))

                if cursor.fetchone()[0] > 0:
                    duplicate_count += 1
                    continue

                cursor.execute("UPDATE listings SET isbn = ? WHERE id = ?", (isbn, listing_id))
                update_count += 1

                if update_count % 100 == 0:
                    conn.commit()
                    print(f"   체크포인트: {update_count:,}개")

            except Exception as e:
                continue

        conn.commit()
        print(f"✅ 완료: {update_count:,}개")
        if duplicate_count > 0:
            print(f"⚠️  중복: {duplicate_count:,}개")
    else:
        print("⚠️  DRY RUN")

    conn.close()

    print()
    print(f"종료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='다른 계정에서 ISBN 복사')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--db', type=str, default='coupang_auto_backup.db')
    parser.add_argument('--account', type=int)
    parser.add_argument('--similarity', type=float, default=0.8, help='최소 유사도 (0.0~1.0)')

    args = parser.parse_args()

    try:
        stats = copy_isbn_from_other_accounts(
            dry_run=args.dry_run,
            limit=args.limit,
            db_path=args.db,
            account_id=args.account,
            min_similarity=args.similarity
        )

        print()
        print(f"📊 성공률: {stats['success']/stats['total']*100:.1f}%")

    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
