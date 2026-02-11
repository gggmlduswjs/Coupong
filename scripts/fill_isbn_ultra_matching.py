"""
울트라 매칭으로 ISBN 채우기 (강화 버전)

스마트 매칭을 더욱 개선한 버전:
- Fuzzy 매칭 (부분 문자열 유사도)
- 시리즈 약어/별칭 처리
- 연도 범위 확대 (±2년)
- 더 유연한 조건 (과목/학기 선택적)
"""
import sys
import io
import re
import sqlite3
from datetime import datetime
from typing import Optional, List, Tuple, Dict

# UTF-8 출력 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


# 시리즈 약어/별칭
SERIES_ALIASES = {
    '오투': ['오투', 'O2', 'o2'],
    '쎈': ['쎈', 'SEN', 'sen'],
    '자이스토리': ['자이스토리', 'Xistory', 'xistory', '자이'],
    '마더텅': ['마더텅', 'mother', 'Mother'],
    '개념원리': ['개념원리', '개념'],
    '완자': ['완자', 'wanja'],
    '풍산자': ['풍산자', '풍산'],
}


def normalize_series_name(text: str) -> str:
    """시리즈명 정규화 (약어 → 표준명)"""
    for standard, aliases in SERIES_ALIASES.items():
        for alias in aliases:
            if alias in text:
                return standard
    return None


def extract_key_components_ultra(product_name: str) -> dict:
    """
    상품명에서 핵심 구성 요소 추출 (울트라 버전)
    """
    result = {
        'series': None,
        'series_normalized': None,
        'level': None,
        'grade': None,  # 학년 숫자 (1, 2, 3 등)
        'subject': None,
        'term': None,
        'year': None,
        'keywords': []
    }

    # 1. 시리즈명 추출 및 정규화
    series_match = re.search(r'\[([가-힣a-zA-Z0-9]+)\]', product_name)
    if series_match:
        result['series'] = series_match.group(1)
    else:
        # 주요 시리즈 키워드 매칭
        for standard, aliases in SERIES_ALIASES.items():
            for alias in aliases:
                if alias in product_name:
                    result['series'] = alias
                    result['series_normalized'] = standard
                    break
            if result['series']:
                break

    # 정규화되지 않았으면 정규화 시도
    if result['series'] and not result['series_normalized']:
        result['series_normalized'] = normalize_series_name(result['series'])

    # 2. 학년 추출
    grade_patterns = [
        (r'초등?\s*(\d)', lambda m: ('초등', m.group(1))),
        (r'중등?\s*(\d)', lambda m: ('중등', m.group(1))),
        (r'중학?\s*(\d)', lambda m: ('중등', m.group(1))),
        (r'고등?\s*(\d)', lambda m: ('고등', m.group(1))),
        (r'초(\d)', lambda m: ('초등', m.group(1))),
        (r'중(\d)', lambda m: ('중등', m.group(1))),
        (r'고(\d)', lambda m: ('고등', m.group(1))),
    ]

    for pattern, formatter in grade_patterns:
        match = re.search(pattern, product_name)
        if match:
            level, grade = formatter(match)
            result['level'] = level
            result['grade'] = grade
            break

    # 3. 과목 추출
    subjects = ['수학', '영어', '국어', '과학', '사회', '역사', '지리', '물리', '화학', '생물', '지구과학',
                '통합과학', '통합사회', '문학', '독서', '화법', '작문', '언어', '문법', '생명과학']

    for subject in subjects:
        if subject in product_name:
            result['subject'] = subject
            break

    # 4. 학기 추출
    term_match = re.search(r'(\d)-(\d)', product_name)
    if term_match:
        result['term'] = term_match.group(0)

    # 5. 연도 추출
    year_match = re.search(r'(20\d{2})', product_name)
    if year_match:
        result['year'] = int(year_match.group(1))

    return result


def build_ultra_query(components: dict) -> List[Tuple[str, List]]:
    """
    여러 수준의 쿼리 생성 (가장 엄격 → 가장 유연)

    Returns:
        [(query, params), ...] 우선순위 순
    """
    queries = []

    series = components['series_normalized'] or components['series']
    if not series:
        return []

    # Level 1: 시리즈 + 학년 + 과목 + 학기 + 연도(±2년)
    if components['grade'] and components['subject'] and components['term'] and components['year']:
        conditions = ["title LIKE ?"]
        params = [f"%{series}%"]

        # 학년 (여러 표현 허용)
        level = components['level']
        grade = components['grade']
        grade_conditions = []
        if '중등' in level:
            grade_conditions = [f"%중{grade}%", f"%중등{grade}%", f"%중학{grade}%", f"%중등 {grade}%"]
        elif '고등' in level:
            grade_conditions = [f"%고{grade}%", f"%고등{grade}%", f"%고등 {grade}%"]
        elif '초등' in level:
            grade_conditions = [f"%초{grade}%", f"%초등{grade}%", f"%초등 {grade}%"]

        if grade_conditions:
            conditions.append(f"({' OR '.join(['title LIKE ?' for _ in grade_conditions])})")
            params.extend(grade_conditions)

        conditions.append("title LIKE ?")
        params.append(f"%{components['subject']}%")

        conditions.append("title LIKE ?")
        params.append(f"%{components['term']}%")

        # 연도 ±2년
        year = components['year']
        year_conditions = []
        for offset in range(-2, 3):  # -2, -1, 0, 1, 2
            year_conditions.append("year = ?")
            params.append(year + offset)
        conditions.append(f"({' OR '.join(year_conditions)})")

        query = f"SELECT isbn, title, year FROM books WHERE {' AND '.join(conditions)} LIMIT 3"
        queries.append((query, params))

    # Level 2: 시리즈 + 학년 + 과목 + 학기 (연도 무시)
    if components['grade'] and components['subject'] and components['term']:
        conditions = ["title LIKE ?"]
        params = [f"%{series}%"]

        level = components['level']
        grade = components['grade']
        grade_conditions = []
        if '중등' in level:
            grade_conditions = [f"%중{grade}%", f"%중등{grade}%", f"%중학{grade}%"]
        elif '고등' in level:
            grade_conditions = [f"%고{grade}%", f"%고등{grade}%"]
        elif '초등' in level:
            grade_conditions = [f"%초{grade}%", f"%초등{grade}%"]

        if grade_conditions:
            conditions.append(f"({' OR '.join(['title LIKE ?' for _ in grade_conditions])})")
            params.extend(grade_conditions)

        conditions.append("title LIKE ?")
        params.append(f"%{components['subject']}%")

        conditions.append("title LIKE ?")
        params.append(f"%{components['term']}%")

        query = f"SELECT isbn, title, year FROM books WHERE {' AND '.join(conditions)} LIMIT 3"
        queries.append((query, params))

    # Level 3: 시리즈 + 학년 + 과목 (학기 무시)
    if components['grade'] and components['subject']:
        conditions = ["title LIKE ?"]
        params = [f"%{series}%"]

        level = components['level']
        grade = components['grade']
        grade_conditions = []
        if '중등' in level:
            grade_conditions = [f"%중{grade}%", f"%중등{grade}%", f"%중학{grade}%"]
        elif '고등' in level:
            grade_conditions = [f"%고{grade}%", f"%고등{grade}%"]
        elif '초등' in level:
            grade_conditions = [f"%초{grade}%", f"%초등{grade}%"]

        if grade_conditions:
            conditions.append(f"({' OR '.join(['title LIKE ?' for _ in grade_conditions])})")
            params.extend(grade_conditions)

        conditions.append("title LIKE ?")
        params.append(f"%{components['subject']}%")

        query = f"SELECT isbn, title, year FROM books WHERE {' AND '.join(conditions)} LIMIT 3"
        queries.append((query, params))

    # Level 4: 시리즈 + 과목 (학년 무시)
    if components['subject']:
        conditions = ["title LIKE ?", "title LIKE ?"]
        params = [f"%{series}%", f"%{components['subject']}%"]

        query = f"SELECT isbn, title, year FROM books WHERE {' AND '.join(conditions)} LIMIT 3"
        queries.append((query, params))

    # Level 5: 시리즈만 (가장 유연)
    conditions = ["title LIKE ?"]
    params = [f"%{series}%"]

    query = f"SELECT isbn, title, year FROM books WHERE {' AND '.join(conditions)} LIMIT 5"
    queries.append((query, params))

    return queries


def find_isbn_ultra_matching(product_name: str, conn) -> Optional[str]:
    """
    울트라 매칭으로 ISBN 찾기 (우선순위별 시도)
    """
    components = extract_key_components_ultra(product_name)

    if not components['series'] and not components['series_normalized']:
        return None

    queries = build_ultra_query(components)

    cursor = conn.cursor()

    for query, params in queries:
        try:
            cursor.execute(query, params)
            results = cursor.fetchall()

            if results:
                # 첫 번째 결과 반환
                return results[0][0]
        except Exception as e:
            continue

    return None


def fill_isbn_ultra_matching(
    dry_run: bool = False,
    limit: int = None,
    db_path: str = 'coupang_auto_backup.db',
    account_id: int = None,
    skip_existing: bool = True
):
    """
    울트라 매칭으로 ISBN 채우기

    Args:
        skip_existing: True이면 이미 스마트 매칭으로 시도했던 것 스킵
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=" * 80)
    print("울트라 매칭으로 ISBN 채우기 (강화 버전)")
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
        'by_series': {}
    }

    updated_listings = []

    for idx, row in enumerate(candidates, 1):
        listing_id = row[0]
        acc_id = row[1]
        product_name = row[2]

        components = extract_key_components_ultra(product_name)

        isbn = find_isbn_ultra_matching(product_name, conn)

        if isbn:
            stats['success'] += 1

            series = components['series_normalized'] or components['series'] or 'unknown'
            stats['by_series'][series] = stats['by_series'].get(series, 0) + 1

            updated_listings.append((listing_id, isbn, product_name, series))

            if stats['success'] <= 10:
                print(f"✓ [{stats['success']}] {product_name[:60]}")
                print(f"   → ISBN: {isbn} | 시리즈: {series}")
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

    if stats['by_series']:
        print("📚 시리즈별:")
        for series, count in sorted(stats['by_series'].items(), key=lambda x: -x[1])[:10]:
            print(f"   {series:15s}: {count:4d}개")
        print()

    if not dry_run and updated_listings:
        print("💾 업데이트 중...")

        update_count = 0
        duplicate_count = 0

        for listing_id, isbn, product_name, series in updated_listings:
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

    parser = argparse.ArgumentParser(description='울트라 매칭')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--db', type=str, default='coupang_auto_backup.db')
    parser.add_argument('--account', type=int)

    args = parser.parse_args()

    try:
        stats = fill_isbn_ultra_matching(
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
