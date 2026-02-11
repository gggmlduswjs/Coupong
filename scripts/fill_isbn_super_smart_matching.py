"""
초강력 스마트 매칭으로 ISBN 채우기

Books 테이블 활용을 극대화:
- 다양한 키워드 조합 시도
- 숫자 공백 처리 (지구과학1 → 지구과학 1)
- EBS/수능특강 패턴 특화
- 출판사명 활용
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


def extract_search_patterns(product_name: str) -> List[str]:
    """
    상품명에서 다양한 검색 패턴 생성
    """
    patterns = []

    # 1. 수능특강 패턴
    if '수능특강' in product_name:
        # "2027학년도 수능특강 지구과학1" → "EBS 수능특강 지구과학 1"
        # "수능특강 화학1" → "수능특강 화학 1"

        # 과목 추출
        subjects = ['물리', '화학', '생명과학', '지구과학', '한국사', '사회문화', '생활과윤리',
                   '윤리와사상', '세계지리', '동아시아사', '세계사', '경제', '정치와법', '사회',
                   '국어', '영어', '수학', '독서', '문학', '언어와매체', '화법과작문']

        for subject in subjects:
            if subject in product_name:
                # 숫자 처리 (물리1 → 물리 1)
                subject_with_space = re.sub(r'(\D)(\d)', r'\1 \2', subject)

                patterns.append(f"수능특강%{subject}%")
                patterns.append(f"EBS 수능특강%{subject}%")
                patterns.append(f"수능특강%{subject_with_space}%")
                break

    # 2. 개념+유형 / 개념원리 패턴
    if '개념' in product_name and '유형' in product_name:
        # "개념+유형 라이트 중학 수학 1-1" → "개념 + 유형 라이트 중학 수학 1-1"
        grade_pattern = re.search(r'(초등|중등|중학|고등)\s*(\d)?', product_name)
        subject = None

        subjects = ['수학', '영어', '국어', '과학', '사회']
        for s in subjects:
            if s in product_name:
                subject = s
                break

        if subject:
            if grade_pattern:
                level = grade_pattern.group(1)
                grade = grade_pattern.group(2) if grade_pattern.group(2) else ''
                patterns.append(f"개념%유형%{level}%{subject}%")
                if grade:
                    patterns.append(f"개념%유형%{level}%{grade}%{subject}%")
            else:
                patterns.append(f"개념%유형%{subject}%")

    # 3. 100발 100중 패턴
    if '100발' in product_name or '100중' in product_name:
        # "100발 100중 중학 영어 3-1(동아 윤정미)" → "100발 100중%중학 영어%"
        grade_pattern = re.search(r'(초등|중등|중학|고등)\s*(\d)?', product_name)
        subject = None

        subjects = ['수학', '영어', '국어', '과학', '사회']
        for s in subjects:
            if s in product_name:
                subject = s
                break

        if subject and grade_pattern:
            level = grade_pattern.group(1)
            patterns.append(f"100발 100중%{level}%{subject}%")

    # 4. 시리즈명 패턴
    series = ['오투', '쎈', '자이스토리', '마더텅', '완자', '한끝', '풍산자', '일품']
    for s in series:
        if s in product_name:
            # "오투 중등 과학 2-1" → "오투%중등%과학%"
            grade_pattern = re.search(r'(초등|중등|중학|고등)\s*(\d)?', product_name)
            subject = None

            subjects_list = ['수학', '영어', '국어', '과학', '사회', '물리', '화학', '생명과학', '지구과학']
            for subj in subjects_list:
                if subj in product_name:
                    subject = subj
                    break

            if subject:
                if grade_pattern:
                    level = grade_pattern.group(1)
                    patterns.append(f"{s}%{level}%{subject}%")
                else:
                    patterns.append(f"{s}%{subject}%")

    # 5. 일반 패턴 (앞 3단어)
    clean = re.sub(r'\([^)]*\)', '', product_name)
    clean = re.sub(r'\+사은품|\+선물|사은품|선물', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()

    words = clean.split()[:3]
    if len(words) >= 2:
        patterns.append('%'.join(words) + '%')

    return patterns


def find_isbn_super_smart(product_name: str, conn) -> Optional[Tuple[str, str, float]]:
    """
    초강력 스마트 매칭으로 ISBN 찾기

    Returns:
        (isbn, matched_title, confidence) 또는 None
    """
    patterns = extract_search_patterns(product_name)

    if not patterns:
        return None

    cursor = conn.cursor()

    for idx, pattern in enumerate(patterns):
        try:
            cursor.execute("""
                SELECT isbn, title
                FROM books
                WHERE title LIKE ?
                LIMIT 1
            """, (pattern,))

            result = cursor.fetchone()
            if result:
                # 신뢰도: 첫 번째 패턴일수록 높음
                confidence = 1.0 - (idx * 0.1)
                return (result[0], result[1], confidence)
        except Exception as e:
            continue

    return None


def fill_isbn_super_smart_matching(
    dry_run: bool = False,
    limit: int = None,
    db_path: str = 'coupang_auto_backup.db',
    account_id: int = None
):
    """
    초강력 스마트 매칭으로 ISBN 채우기
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=" * 80)
    print("초강력 스마트 매칭으로 ISBN 채우기")
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
        'by_confidence': {
            '90-100%': 0,
            '80-90%': 0,
            '70-80%': 0,
        }
    }

    updated_listings = []

    for idx, row in enumerate(candidates, 1):
        listing_id = row[0]
        acc_id = row[1]
        product_name = row[2]

        result = find_isbn_super_smart(product_name, conn)

        if result:
            isbn, matched_title, confidence = result
            stats['success'] += 1

            # 신뢰도 분류
            if confidence >= 0.9:
                stats['by_confidence']['90-100%'] += 1
            elif confidence >= 0.8:
                stats['by_confidence']['80-90%'] += 1
            else:
                stats['by_confidence']['70-80%'] += 1

            updated_listings.append((listing_id, isbn, product_name, matched_title, confidence))

            if stats['success'] <= 20:
                print(f"✓ [{stats['success']}] {product_name[:60]}")
                print(f"   → ISBN: {isbn} | 신뢰도: {confidence*100:.0f}%")
                print(f"   ← {matched_title[:60]}")
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
        print("📊 신뢰도 분포:")
        for range_name, count in sorted(stats['by_confidence'].items(), reverse=True):
            if count > 0:
                print(f"   {range_name}: {count:4d}개 ({count/stats['success']*100:.1f}%)")
        print()

    if not dry_run and updated_listings:
        print("💾 업데이트 중...")

        update_count = 0
        duplicate_count = 0

        for listing_id, isbn, product_name, matched_title, confidence in updated_listings:
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

    parser = argparse.ArgumentParser(description='초강력 스마트 매칭')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--db', type=str, default='coupang_auto_backup.db')
    parser.add_argument('--account', type=int)

    args = parser.parse_args()

    try:
        stats = fill_isbn_super_smart_matching(
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
