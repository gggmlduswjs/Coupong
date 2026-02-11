"""
ISBN 충족률 리포트 생성 스크립트

현재 ISBN 보유 현황을 분석하고 상세 리포트를 생성합니다.
- 전체 통계
- 계정별 통계
- 소스별 통계 (raw_json, books, aladin_api)
- 묶음 vs 단일 상품
"""
import sys
import io
from pathlib import Path
from datetime import datetime
from typing import Dict, List

# UTF-8 출력 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import sqlite3


def generate_isbn_report(db_path: str = 'coupang_auto_backup.db'):
    """ISBN 충족률 리포트 생성"""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("=" * 80)
    print("ISBN 충족률 리포트")
    print("=" * 80)
    print(f"생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"데이터베이스: {db_path}")
    print()

    # ============================================================================
    # 1. 전체 통계
    # ============================================================================
    cursor.execute("SELECT COUNT(*) FROM listings")
    total_listings = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM listings WHERE isbn IS NOT NULL AND isbn != ''")
    with_isbn = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM listings WHERE isbn IS NULL OR isbn = ''")
    without_isbn = cursor.fetchone()[0]

    print("📊 전체 통계")
    print("-" * 80)
    print(f"총 상품 수: {total_listings:,}개")
    print(f"ISBN 보유: {with_isbn:,}개 ({with_isbn/total_listings*100:.2f}%)")
    print(f"ISBN 없음: {without_isbn:,}개 ({without_isbn/total_listings*100:.2f}%)")
    print()

    # ============================================================================
    # 2. 상품 유형별 통계
    # ============================================================================
    cursor.execute("""
        SELECT product_type, COUNT(*) as cnt
        FROM listings
        GROUP BY product_type
    """)
    type_stats = cursor.fetchall()

    print("📦 상품 유형별 통계")
    print("-" * 80)
    for row in type_stats:
        ptype = row[0] or 'unknown'
        count = row[1]
        print(f"{ptype}: {count:,}개 ({count/total_listings*100:.1f}%)")

        # 유형별 ISBN 보유율
        cursor.execute("""
            SELECT COUNT(*) FROM listings
            WHERE product_type = ? AND isbn IS NOT NULL AND isbn != ''
        """, (row[0],))
        with_isbn_type = cursor.fetchone()[0]
        print(f"  └─ ISBN 보유: {with_isbn_type:,}개 ({with_isbn_type/count*100:.1f}%)")
    print()

    # ============================================================================
    # 3. 계정별 통계
    # ============================================================================
    cursor.execute("""
        SELECT
            l.account_id,
            a.account_name,
            COUNT(*) as total,
            SUM(CASE WHEN l.isbn IS NOT NULL AND l.isbn != '' THEN 1 ELSE 0 END) as with_isbn
        FROM listings l
        LEFT JOIN accounts a ON l.account_id = a.id
        GROUP BY l.account_id
        ORDER BY l.account_id
    """)
    account_stats = cursor.fetchall()

    print("👤 계정별 통계")
    print("-" * 80)
    for row in account_stats:
        acc_id = row[0]
        acc_name = row[1] or f'Account {acc_id}'
        total = row[2]
        with_isbn_acc = row[3]
        pct = with_isbn_acc/total*100 if total > 0 else 0

        print(f"{acc_name} (ID:{acc_id})")
        print(f"  총 상품: {total:,}개")
        print(f"  ISBN 보유: {with_isbn_acc:,}개 ({pct:.1f}%)")
        print()

    # ============================================================================
    # 4. ISBN 형태 분석 (단일 vs 복수)
    # ============================================================================
    cursor.execute("""
        SELECT
            CASE
                WHEN isbn LIKE '%,%' THEN '복수 ISBN (묶음)'
                WHEN isbn IS NOT NULL AND isbn != '' THEN '단일 ISBN'
                ELSE 'ISBN 없음'
            END as isbn_type,
            COUNT(*) as cnt
        FROM listings
        GROUP BY isbn_type
    """)
    isbn_type_stats = cursor.fetchall()

    print("📚 ISBN 형태 분석")
    print("-" * 80)
    for row in isbn_type_stats:
        itype = row[0]
        count = row[1]
        print(f"{itype}: {count:,}개 ({count/total_listings*100:.1f}%)")
    print()

    # ============================================================================
    # 5. raw_json 보유 현황
    # ============================================================================
    cursor.execute("""
        SELECT
            CASE
                WHEN raw_json IS NOT NULL AND raw_json != '' THEN 'raw_json 있음'
                ELSE 'raw_json 없음'
            END as has_raw,
            COUNT(*) as cnt
        FROM listings
        GROUP BY has_raw
    """)
    raw_json_stats = cursor.fetchall()

    print("🔍 raw_json 보유 현황")
    print("-" * 80)
    for row in raw_json_stats:
        has_raw = row[0]
        count = row[1]
        print(f"{has_raw}: {count:,}개 ({count/total_listings*100:.1f}%)")

        if 'raw_json 있음' in has_raw:
            # raw_json은 있지만 ISBN이 없는 경우
            cursor.execute("""
                SELECT COUNT(*) FROM listings
                WHERE raw_json IS NOT NULL AND raw_json != ''
                AND (isbn IS NULL OR isbn = '')
            """)
            no_isbn_with_raw = cursor.fetchone()[0]
            print(f"  └─ ISBN 없음: {no_isbn_with_raw:,}개 (Phase 1 대상)")
    print()

    # ============================================================================
    # 6. 묶음 패턴 상품 분석
    # ============================================================================
    cursor.execute("""
        SELECT COUNT(*) FROM listings
        WHERE (product_name LIKE '%+%'
            OR product_name LIKE '%&%'
            OR product_name LIKE '%세트%'
            OR product_name LIKE '%전%권%')
        AND (isbn IS NULL OR isbn = '')
    """)
    bundle_candidates = cursor.fetchone()[0]

    print("📦 묶음 패턴 상품 (ISBN 없음)")
    print("-" * 80)
    print(f"묶음 패턴 포함: {bundle_candidates:,}개 (Phase 2 대상)")
    print()

    # ============================================================================
    # 7. 알라딘 API 검색 대상
    # ============================================================================
    cursor.execute("""
        SELECT COUNT(*) FROM listings
        WHERE (isbn IS NULL OR isbn = '')
        AND product_name IS NOT NULL AND product_name != ''
    """)
    api_candidates = cursor.fetchone()[0]

    print("🔍 알라딘 API 검색 대상")
    print("-" * 80)
    print(f"상품명 있음 & ISBN 없음: {api_candidates:,}개 (Phase 3 대상)")
    print()

    # ============================================================================
    # 8. 목표 달성률
    # ============================================================================
    current_rate = with_isbn / total_listings * 100
    target_rate = 85.0
    remaining_to_target = int(total_listings * target_rate / 100) - with_isbn

    print("🎯 목표 달성률")
    print("-" * 80)
    print(f"현재: {with_isbn:,}/{total_listings:,} ({current_rate:.2f}%)")
    print(f"목표: 85%")
    print(f"필요: 추가 {remaining_to_target:,}개 ISBN")
    print()

    if current_rate >= target_rate:
        print("✅ 목표 달성!")
    else:
        gap = target_rate - current_rate
        print(f"📈 목표까지: {gap:.2f}%p")

        # 단계별 예상 성과
        print()
        print("예상 단계별 성과:")
        phase1_est = 537  # 실제 추출 결과
        phase2_est = 500  # 보수적 추정
        phase3_est = 1200  # 보수적 추정

        total_est = with_isbn + phase1_est + phase2_est + phase3_est
        est_rate = total_est / total_listings * 100

        print(f"  Phase 1 (raw_json): +{phase1_est:,}개")
        print(f"  Phase 2 (묶음): +{phase2_est:,}개")
        print(f"  Phase 3 (알라딘 API): +{phase3_est:,}개")
        print(f"  예상 최종: {total_est:,}개 ({est_rate:.2f}%)")

    print()
    print("=" * 80)

    conn.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='ISBN 충족률 리포트 생성')
    parser.add_argument('--db', type=str, default='coupang_auto_backup.db', help='DB 파일 경로')

    args = parser.parse_args()

    try:
        generate_isbn_report(db_path=args.db)
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
