"""알라딘 API로 나머지 ISBN 채우기"""
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

    # +, & 기호 제거 (세트 구분자)
    title = re.sub(r'\s*[+&]\s*', ' ', title)

    # 불필요한 키워드 제거
    remove_words = ['선물', '사은품', '증정', '포함', '무료배송']
    for word in remove_words:
        title = title.replace(word, '')

    # 공백 정리
    title = ' '.join(title.split())

    # 앞부분만 사용 (너무 길면 검색 안됨)
    words = title.split()[:5]  # 처음 5단어만

    return ' '.join(words).strip()


def search_isbn_from_aladin(product_name):
    """알라딘 API로 ISBN 검색"""
    keyword = clean_title_for_search(product_name)

    if not keyword or len(keyword) < 3:
        return []

    try:
        # 알라딘 API 검색 (최대 5개)
        results = crawler.search_by_keyword(
            keyword=keyword,
            max_results=5,
            sort="Accuracy"  # 관련도순
        )

        if not results:
            return []

        # ISBN 추출
        isbns = []
        for item in results:
            isbn = item.get('isbn13') or item.get('isbn')
            if isbn:
                isbns.append(isbn)

        return isbns

    except Exception as e:
        print(f'  [알라딘 API 에러] {str(e)[:50]}')
        return []


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
        print(f'\n=== 알라딘 API로 ISBN 채우기 (007-book) ===')
        print(f'처리 대상: {total}개')
        print(f'방법: product_name → 알라딘 API 검색 → ISBN\n')

        filled = 0
        failed = 0
        skipped = 0

        for i, (lid, aid, pname, cpid) in enumerate(rows):
            if i % 20 == 0:
                print(f'  [{i}/{total}] filled={filled}, failed={failed}, skipped={skipped}', flush=True)

            try:
                # 알라딘 API 검색
                isbns = search_isbn_from_aladin(pname)

                if isbns:
                    # 최대 3개까지만
                    isbn_str = ",".join(isbns[:3])

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
                            print(f'  [성공] {pname[:40]}... → {isbn_str}')

                        if filled % 50 == 0:
                            conn.commit()

                else:
                    failed += 1
                    if failed <= 5:  # 처음 5개만 출력
                        print(f'  [실패] {pname[:40]}... → 검색 결과 없음')

                # API 호출 제한 (1초 대기)
                time.sleep(1.0)

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
