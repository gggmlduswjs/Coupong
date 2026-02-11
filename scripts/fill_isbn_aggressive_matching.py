"""
공격적 매칭으로 ISBN 채우기

상품명을 극도로 정제한 후 Books 테이블 매칭:
- (사은품), (선물), +사은품 등 제거
- 괄호 제거 후 재매칭
- 더 유연한 유사도 기준
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


def aggressive_clean_product_name(name: str) -> str:
    """
    상품명을 극도로 정제
    """
    if not name:
        return ""

    # 1. 사은품/선물 관련 모두 제거
    patterns = [
        r'\(사은품\)',
        r'\(선물\)',
        r'\+사은품',
        r'\+선물',
        r'사은품\+',
        r'선물\+',
        r'사은품',
        r'선물',
        r'증정',
    ]

    cleaned = name
    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    # 2. 모든 괄호 제거
    cleaned = re.sub(r'\([^)]*\)', '', cleaned)
    cleaned = re.sub(r'\[[^\]]*\]', '', cleaned)

    # 3. + & 세트 등 제거
    cleaned = re.sub(r'\s*\+\s*', ' ', cleaned)
    cleaned = re.sub(r'\s*&\s*', ' ', cleaned)
    cleaned = re.sub(r'세트', '', cleaned)

    # 4. 연속 공백 제거
    cleaned = re.sub(r'\s+', ' ', cleaned)

    return cleaned.strip()


def find_isbn_from_books_aggressive(product_name: str, conn) -> Optional[str]:
    """
    공격적 매칭으로 Books 테이블에서 ISBN 찾기
    """
    cleaned = aggressive_clean_product_name(product_name)

    if not cleaned or len(cleaned) < 5:
        return None

    cursor = conn.cursor()

    # 전체 제목 검색
    cursor.execute("""
        SELECT isbn, title FROM books
        WHERE title LIKE ?
        LIMIT 1
    """, (f"%{cleaned}%",))

    result = cursor.fetchone()
    if result:
        return result[0]

    # 키워드 추출 (공백 기준 분리)
    words = cleaned.split()
    if len(words) >= 3:
        # 앞 3단어로 검색
        keyword = ' '.join(words[:3])
        cursor.execute("""
            SELECT isbn, title FROM books
            WHERE title LIKE ?
            LIMIT 1
        """, (f"%{keyword}%",))

        result = cursor.fetchone()
        if result:
            return result[0]

    return None


def fill_isbn_aggressive_matching(
    dry_run: bool = False,
    limit: int = None,
    db_path: str = 'coupang_auto_backup.db',
    account_id: int = None
):
    """
    공격적 매칭으로 ISBN 채우기
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=" * 80)
    print("공격적 매칭으로 ISBN 채우기")
    print("=" * 80)
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모드: {'DRY RUN' if dry_run else 'LIVE'}")
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
    }

    updated_listings = []

    for idx, row in enumerate(candidates, 1):
        listing_id = row[0]
        acc_id = row[1]
        product_name = row[2]

        isbn = find_isbn_from_books_aggressive(product_name, conn)

        if isbn:
            stats['success'] += 1
            updated_listings.append((listing_id, isbn, product_name))

            if stats['success'] <= 20:
                print(f"✓ [{stats['success']}] {product_name[:60]}")
                print(f"   → ISBN: {isbn}")
                print(f"   정제: {aggressive_clean_product_name(product_name)[:60]}")
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

    if not dry_run and updated_listings:
        print("💾 업데이트 중...")

        update_count = 0
        duplicate_count = 0

        for listing_id, isbn, product_name in updated_listings:
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

    parser = argparse.ArgumentParser(description='공격적 매칭')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--db', type=str, default='coupang_auto_backup.db')
    parser.add_argument('--account', type=int)

    args = parser.parse_args()

    try:
        stats = fill_isbn_aggressive_matching(
            dry_run=args.dry_run,
            limit=args.limit,
            db_path=args.db,
            account_id=args.account
        )

        print()
        print(f"📊 성공률: {stats['success']/stats['total']*100:.1f}%")

    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
