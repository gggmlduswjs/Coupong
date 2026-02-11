"""상품명으로 books 테이블 매칭하여 ISBN 채우기"""
import sys, os, re

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text, create_engine

# 백업 DB 사용
DB_PATH = r'C:\Users\user\Desktop\Coupong\coupang_auto_backup.db'
engine = create_engine(f'sqlite:///{DB_PATH}')


def normalize_title(title):
    """제목 정규화 (매칭용)"""
    if not title:
        return ""

    # 소문자 변환
    title = title.lower()

    # 제거할 패턴들
    patterns = [
        r'\(세트\d*\)',  # (세트1), (세트)
        r'세트\d*',      # 세트1, 세트
        r'\d{4}년',      # 2026년, 2027년
        r'\(\d{4}\)',    # (2026), (2027)
        r'\(.*?판\)',    # (개정판), (신판)
        r'\s+',          # 연속 공백 → 단일 공백
    ]

    for pattern in patterns:
        title = re.sub(pattern, ' ', title)

    # 앞뒤 공백 제거
    title = title.strip()

    return title


def extract_keywords(product_name):
    """상품명에서 핵심 키워드 추출"""
    # 괄호 안의 출판사/저자 정보 추출
    publisher_match = re.search(r'\((.*?)\)', product_name)
    publisher = publisher_match.group(1) if publisher_match else ""

    # 괄호 제거
    clean_name = re.sub(r'\([^)]*\)', '', product_name)

    # 연도 제거
    clean_name = re.sub(r'\d{4}년?', '', clean_name)
    clean_name = re.sub(r'20\d{2}', '', clean_name)

    # 세트 제거
    clean_name = re.sub(r'세트\d*', '', clean_name)

    # 공백 정리
    clean_name = ' '.join(clean_name.split())

    return clean_name.lower(), publisher.lower()


def find_matching_books(product_name, conn):
    """상품명으로 books 테이블에서 매칭되는 책 찾기"""
    if not product_name:
        return []

    # 키워드 추출
    keywords, publisher = extract_keywords(product_name)

    # 너무 짧으면 매칭 안 함
    if len(keywords) < 5:
        return []

    # 여러 단계로 매칭 시도
    results = []

    # 1단계: 전체 키워드 + 출판사 매칭
    if publisher:
        query = text("""
            SELECT DISTINCT b.isbn, b.title, b.normalized_title, pub.name as publisher_name
            FROM books b
            LEFT JOIN publishers pub ON b.publisher_id = pub.id
            WHERE LOWER(b.title) LIKE :keyword
            AND LOWER(pub.name) LIKE :pub
            LIMIT 5
        """)
        results = conn.execute(query, {
            'keyword': f'%{keywords[:40]}%',
            'pub': f'%{publisher}%'
        }).fetchall()

    # 2단계: 전체 키워드만으로 매칭
    if not results:
        query = text("""
            SELECT DISTINCT b.isbn, b.title, b.normalized_title, pub.name as publisher_name
            FROM books b
            LEFT JOIN publishers pub ON b.publisher_id = pub.id
            WHERE LOWER(b.title) LIKE :keyword
            LIMIT 5
        """)
        results = conn.execute(query, {
            'keyword': f'%{keywords[:40]}%'
        }).fetchall()

    # 3단계: 앞부분 키워드 (시리즈명)로 매칭
    if not results:
        short_key = keywords.split()[0] if keywords.split() else keywords[:15]
        if len(short_key) >= 3:
            results = conn.execute(query, {
                'keyword': f'%{short_key}%'
            }).fetchall()

    return results


def main():
    with engine.connect() as conn:
        # 007-book 계정, ISBN이 NULL인 listings 조회
        rows = conn.execute(text("""
            SELECT id, account_id, product_name, coupang_product_id
            FROM listings
            WHERE isbn IS NULL
            AND product_name IS NOT NULL
            AND product_name != ''
            AND account_id = 1
            ORDER BY id
        """)).fetchall()

        total = len(rows)
        print(f'\n=== 상품명 매칭으로 ISBN 채우기 (007-book) ===')
        print(f'처리 대상: {total}개')
        print(f'방법: product_name → books 테이블 매칭\n')

        filled = 0
        failed = 0
        skipped = 0

        for i, (lid, aid, pname, cpid) in enumerate(rows):
            if i % 20 == 0:
                print(f'  [{i}/{total}] filled={filled}, failed={failed}, skipped={skipped}', flush=True)

            try:
                # books 테이블에서 매칭
                matches = find_matching_books(pname, conn)

                if matches:
                    # 매칭된 ISBN들 (최대 5개)
                    isbns = [m[0] for m in matches[:5]]
                    isbn_str = ",".join(isbns)

                    # 중복 체크
                    dup = conn.execute(text(
                        'SELECT 1 FROM listings WHERE account_id=:aid AND isbn=:isbn'
                    ), {'aid': aid, 'isbn': isbn_str}).first()

                    if dup:
                        skipped += 1
                    else:
                        # DB 업데이트
                        conn.execute(text(
                            'UPDATE listings SET isbn=:isbn WHERE id=:lid'
                        ), {'isbn': isbn_str, 'lid': lid})

                        filled += 1
                        if filled <= 10:  # 처음 10개만 출력
                            print(f'  [성공] {pname[:40]}... → ISBN: {isbn_str}')

                        if filled % 50 == 0:
                            conn.commit()
                else:
                    failed += 1
                    if failed <= 5:  # 처음 5개만 출력
                        print(f'  [실패] {pname[:40]}... → 매칭 없음')

            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f'  [에러] listing_id={lid}: {str(e)[:100]}')

        conn.commit()
        print(f'\n완료: filled={filled}, failed={failed}, skipped={skipped}')

        # 최종 통계
        f = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NOT NULL')).scalar()
        n = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NULL')).scalar()
        print(f'최종: ISBN있음={f}, NULL={n}')


if __name__ == '__main__':
    main()
