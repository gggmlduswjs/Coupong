"""
스마트 매칭으로 ISBN 채우기

Books 테이블과 향상된 매칭 알고리즘으로 ISBN을 채웁니다.
- 시리즈명 + 학년 + 학기 + 과목 조합 매칭
- Fuzzy 매칭 (부분 문자열)
- 연도 고려 (±1년 허용)
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


def extract_key_components(product_name: str) -> dict:
    """
    상품명에서 핵심 구성 요소 추출

    Returns:
        {
            'series': 시리즈명 (오투, 마더텅 등),
            'level': 학년 (초등, 중등, 고등, 중1, 고2 등),
            'subject': 과목 (수학, 영어, 과학 등),
            'term': 학기 (1-1, 2-1 등),
            'year': 연도 (2026 등),
            'keywords': 주요 키워드 리스트
        }
    """
    result = {
        'series': None,
        'level': None,
        'subject': None,
        'term': None,
        'year': None,
        'keywords': []
    }

    # 1. 시리즈명 추출 (대괄호 또는 처음 단어)
    series_match = re.search(r'\[([가-힣a-zA-Z]+)\]', product_name)
    if series_match:
        result['series'] = series_match.group(1)
    else:
        # 주요 시리즈 키워드 매칭
        for series in ['마더텅', '자이스토리', '오투', '완자', '쎈', '한끝', '개념', '풍산자', '일품', '수능특강', '개념원리']:
            if series in product_name:
                result['series'] = series
                break

    # 2. 학년 추출
    level_patterns = [
        (r'초등\s*(\d)', lambda m: f'초등 {m.group(1)}'),
        (r'중등\s*(\d)', lambda m: f'중등 {m.group(1)}'),
        (r'중학?\s*(\d)', lambda m: f'중등 {m.group(1)}'),
        (r'고등?\s*(\d)', lambda m: f'고등 {m.group(1)}'),
        (r'초등', lambda m: '초등'),
        (r'중등', lambda m: '중등'),
        (r'중학', lambda m: '중등'),
        (r'고등', lambda m: '고등'),
    ]

    for pattern, formatter in level_patterns:
        match = re.search(pattern, product_name)
        if match:
            result['level'] = formatter(match)
            break

    # 3. 과목 추출
    subjects = ['수학', '영어', '국어', '과학', '사회', '역사', '지리', '물리', '화학', '생물', '지구과학',
                '통합과학', '통합사회', '문학', '독서', '화법', '작문', '언어', '문법']

    for subject in subjects:
        if subject in product_name:
            result['subject'] = subject
            break

    # 4. 학기 추출 (1-1, 2-2 등)
    term_match = re.search(r'(\d)-(\d)', product_name)
    if term_match:
        result['term'] = term_match.group(0)

    # 5. 연도 추출
    year_match = re.search(r'(20\d{2})', product_name)
    if year_match:
        result['year'] = int(year_match.group(1))

    # 6. 모든 의미 있는 키워드 추출 (2글자 이상)
    keywords = re.findall(r'[가-힣a-zA-Z]{2,}', product_name)

    # 불용어 제거
    stopwords = {'선물', '사은품', '증정', '포함', '무료', '세트'}
    result['keywords'] = [k for k in keywords if k not in stopwords]

    return result


def build_smart_query(components: dict) -> Tuple[str, List]:
    """
    추출된 구성 요소로 SQL 쿼리 생성

    Returns:
        (query_string, parameters)
    """
    conditions = []
    params = []

    # 필수: 시리즈명
    if components['series']:
        conditions.append("title LIKE ?")
        params.append(f"%{components['series']}%")

    # 선택: 과목
    if components['subject']:
        conditions.append("title LIKE ?")
        params.append(f"%{components['subject']}%")

    # 선택: 학년
    if components['level']:
        # "중등 2" → "중2", "중학 2", "중등2" 등 모두 매칭
        if '중등' in components['level']:
            grade_num = re.search(r'\d', components['level'] or '')
            if grade_num:
                conditions.append("(title LIKE ? OR title LIKE ? OR title LIKE ?)")
                num = grade_num.group()
                params.extend([f'%중{num}%', f'%중등{num}%', f'%중학{num}%'])
            else:
                conditions.append("(title LIKE ? OR title LIKE ?)")
                params.extend(['%중등%', '%중학%'])
        else:
            conditions.append("title LIKE ?")
            params.append(f"%{components['level']}%")

    # 선택: 학기
    if components['term']:
        conditions.append("title LIKE ?")
        params.append(f"%{components['term']}%")

    # 선택: 연도 (±1년 허용)
    if components['year']:
        year_conditions = []
        for offset in [-1, 0, 1]:
            year_conditions.append("year = ?")
            params.append(components['year'] + offset)
        conditions.append(f"({' OR '.join(year_conditions)})")

    if not conditions:
        return None, None

    query = f"""
        SELECT isbn, title, year, publisher_name
        FROM books
        WHERE {' AND '.join(conditions)}
        LIMIT 5
    """

    return query, params


def find_isbn_smart_matching(product_name: str, conn) -> Optional[str]:
    """
    스마트 매칭으로 ISBN 찾기

    Returns:
        ISBN 또는 None
    """
    # 1. 구성 요소 추출
    components = extract_key_components(product_name)

    # 시리즈가 없으면 매칭 불가
    if not components['series']:
        return None

    # 2. 쿼리 생성
    query, params = build_smart_query(components)

    if not query:
        return None

    # 3. 검색
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = cursor.fetchall()

        if results:
            # 첫 번째 결과의 ISBN 반환
            return results[0][0]

    except Exception as e:
        print(f"  [검색 에러] {str(e)[:50]}")

    return None


def fill_isbn_smart_matching(
    dry_run: bool = False,
    limit: int = None,
    db_path: str = 'coupang_auto_backup.db',
    account_id: int = None
):
    """
    스마트 매칭으로 ISBN 채우기

    Args:
        dry_run: 미리보기 모드
        limit: 처리 제한
        db_path: DB 경로
        account_id: 특정 계정만 처리
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=" * 80)
    print("스마트 매칭으로 ISBN 채우기")
    print("=" * 80)
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모드: {'DRY RUN (미리보기)' if dry_run else 'LIVE (실제 업데이트)'}")
    if limit:
        print(f"제한: 최대 {limit}개")
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

    print(f"🔍 대상 레코드: {len(candidates):,}개")
    print()

    # 통계
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

        # 구성 요소 추출
        components = extract_key_components(product_name)

        # ISBN 검색
        isbn = find_isbn_smart_matching(product_name, conn)

        if isbn:
            stats['success'] += 1

            # 시리즈별 통계
            series = components['series'] or 'unknown'
            stats['by_series'][series] = stats['by_series'].get(series, 0) + 1

            updated_listings.append((listing_id, isbn, product_name, series))

            # 처음 10개만 출력
            if stats['success'] <= 10:
                print(f"✓ [{stats['success']}] {product_name[:60]}")
                print(f"   → ISBN: {isbn} | 시리즈: {components['series']}")
        else:
            stats['failed'] += 1

        # 진행 상황 (100개마다)
        if idx % 100 == 0:
            print(f"진행: {idx:,}/{len(candidates):,} ({idx/len(candidates)*100:.1f}%) - "
                  f"성공: {stats['success']:,}")

    print()
    print("=" * 80)
    print("처리 결과")
    print("=" * 80)
    print(f"총 처리: {stats['total']:,}개")
    print(f"✅ 성공: {stats['success']:,}개 ({stats['success']/stats['total']*100:.1f}%)")
    print(f"❌ 실패: {stats['failed']:,}개")
    print()

    if stats['by_series']:
        print("📚 시리즈별 성공 건수:")
        for series, count in sorted(stats['by_series'].items(), key=lambda x: -x[1])[:10]:
            print(f"   {series:15s}: {count:4d}개")
        print()

    if not dry_run and updated_listings:
        print("💾 데이터베이스 업데이트 중...")

        update_count = 0
        duplicate_count = 0

        for listing_id, isbn, product_name, series in updated_listings:
            try:
                cursor = conn.cursor()

                # 계정 ID 조회
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

                # 업데이트
                cursor.execute("UPDATE listings SET isbn = ? WHERE id = ?", (isbn, listing_id))
                update_count += 1

                if update_count % 100 == 0:
                    conn.commit()
                    print(f"   체크포인트: {update_count:,}개 커밋됨")

            except Exception as e:
                print(f"⚠️  ID {listing_id} 업데이트 실패: {e}")
                continue

        conn.commit()
        print(f"✅ 업데이트 완료: {update_count:,}개")
        if duplicate_count > 0:
            print(f"⚠️  중복 스킵: {duplicate_count:,}개")
    else:
        print("⚠️  DRY RUN 모드 - 변경사항이 저장되지 않았습니다")

    conn.close()

    print()
    print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='스마트 매칭으로 ISBN 채우기')
    parser.add_argument('--dry-run', action='store_true', help='미리보기 모드')
    parser.add_argument('--limit', type=int, help='처리 제한')
    parser.add_argument('--db', type=str, default='coupang_auto_backup.db', help='DB 경로')
    parser.add_argument('--account', type=int, help='특정 계정만 처리')

    args = parser.parse_args()

    try:
        stats = fill_isbn_smart_matching(
            dry_run=args.dry_run,
            limit=args.limit,
            db_path=args.db,
            account_id=args.account
        )

        print()
        print("📊 최종 통계:")
        print(f"   성공률: {stats['success']/stats['total']*100:.1f}%")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
