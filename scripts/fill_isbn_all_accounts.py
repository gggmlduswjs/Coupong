"""모든 계정의 ISBN을 알라딘 API로 채우기"""
import sys, os, re, time

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text, create_engine
from crawlers.aladin_api_crawler import AladinAPICrawler

# 백업 DB 사용
DB_PATH = r'C:\Users\user\Desktop\Coupong\coupang_auto_backup.db'
engine = create_engine(f'sqlite:///{DB_PATH}')

# 알라딘 API 초기화
TTB_KEY = os.getenv('ALADIN_TTB_KEY')
if not TTB_KEY:
    print('ALADIN_TTB_KEY 환경변수가 필요합니다.')
    sys.exit(1)

crawler = AladinAPICrawler(TTB_KEY)


def clean_title_for_search(product_name):
    """상품명을 알라딘 검색용 키워드로 정리"""
    if not product_name:
        return ""

    # 괄호 제거
    title = re.sub(r'\([^)]*\)', '', product_name)

    # 연도 제거
    title = re.sub(r'\d{4}년?', '', title)
    title = re.sub(r'20\d{2}', '', title)

    # 세트, 권수 제거
    title = re.sub(r'세트\d*', '', title)
    title = re.sub(r'전\s*\d+권', '', title)
    title = re.sub(r'\d+권', '', title)

    # +, & 기호 제거
    title = re.sub(r'\s*[+&]\s*', ' ', title)

    # 불필요한 키워드 제거
    remove_words = ['선물', '사은품', '증정', '포함', '무료배송']
    for word in remove_words:
        title = title.replace(word, '')

    # 공백 정리
    title = ' '.join(title.split())

    # 앞부분만 사용
    words = title.split()[:5]

    return ' '.join(words).strip()


def search_isbn_from_aladin(product_name):
    """알라딘 API로 ISBN 검색"""
    keyword = clean_title_for_search(product_name)

    if not keyword or len(keyword) < 3:
        return []

    try:
        results = crawler.search_by_keyword(
            keyword=keyword,
            max_results=5,
            sort="Accuracy"
        )

        if not results:
            return []

        isbns = []
        for item in results:
            isbn = item.get('isbn13') or item.get('isbn')
            if isbn:
                isbns.append(isbn)

        return isbns

    except Exception as e:
        return []


def process_account(account_id, account_name, conn):
    """특정 계정의 ISBN 채우기"""
    # ISBN이 NULL인 listings 조회
    rows = conn.execute(text("""
        SELECT id, product_name
        FROM listings
        WHERE isbn IS NULL
        AND product_name IS NOT NULL
        AND product_name != ''
        AND account_id = :aid
        ORDER BY id
    """), {'aid': account_id}).fetchall()

    total = len(rows)
    if total == 0:
        print(f'  {account_name}: 처리할 항목 없음\n')
        return

    print(f'\n=== {account_name} 계정 처리 ===')
    print(f'처리 대상: {total}개\n')

    filled = 0
    failed = 0
    skipped = 0

    for i, (lid, pname) in enumerate(rows):
        if i % 50 == 0:
            print(f'  [{i}/{total}] filled={filled}, failed={failed}, skipped={skipped}', flush=True)

        try:
            isbns = search_isbn_from_aladin(pname)

            if isbns:
                isbn_str = ",".join(isbns[:3])

                # ISBN 저장 (중복 체크 제거 - 각 listing은 고유하므로)
                conn.execute(text(
                    'UPDATE listings SET isbn=:isbn WHERE id=:lid'
                ), {'isbn': isbn_str, 'lid': lid})

                filled += 1
                if filled % 100 == 0:
                    conn.commit()
            else:
                failed += 1

            # API 호출 제한 (1초)
            time.sleep(1.0)

        except Exception as e:
            failed += 1

    conn.commit()
    print(f'\n{account_name} 완료: filled={filled}, failed={failed}, skipped={skipped}')


def main():
    with engine.connect() as conn:
        # 모든 활성 계정 조회
        accounts = conn.execute(text(
            'SELECT id, account_name FROM accounts WHERE is_active=true ORDER BY account_name'
        )).fetchall()

        print('=== 전체 계정 ISBN 채우기 (알라딘 API) ===')
        print(f'대상 계정: {len(accounts)}개\n')

        for aid, aname in accounts:
            process_account(aid, aname, conn)

        # 최종 통계
        print('\n' + '='*60)
        print('=== 최종 통계 ===\n')

        result = conn.execute(text('''
            SELECT a.account_name,
                   COUNT(*) as total,
                   SUM(CASE WHEN l.isbn IS NOT NULL THEN 1 ELSE 0 END) as has_isbn,
                   SUM(CASE WHEN l.isbn IS NULL THEN 1 ELSE 0 END) as null_isbn
            FROM listings l
            JOIN accounts a ON l.account_id = a.id
            GROUP BY a.account_name
            ORDER BY a.account_name
        ''')).fetchall()

        for name, tot, has, null in result:
            pct = has/tot*100 if tot > 0 else 0
            print(f'{name:12s}: 전체 {tot:5,d}개 | ISBN {has:5,d}개 ({pct:5.1f}%) | NULL {null:5,d}개')

        # 전체 통계
        total_all = conn.execute(text('SELECT COUNT(*) FROM listings')).scalar()
        has_all = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NOT NULL')).scalar()
        null_all = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NULL')).scalar()

        print(f'\n전체 합계   : 전체 {total_all:5,d}개 | ISBN {has_all:5,d}개 ({has_all/total_all*100:5.1f}%) | NULL {null_all:5,d}개')


if __name__ == '__main__':
    main()
