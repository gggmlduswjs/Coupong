"""알라딘 API 검색으로 listings ISBN 채우기 (2차 패스)"""
import sys, os, time, re

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from crawlers.aladin_api_crawler import AladinAPICrawler

engine = create_engine('sqlite:///coupang_auto.db')
ttb_key = os.getenv("ALADIN_TTB_KEY", "")

if not ttb_key:
    print("ALADIN_TTB_KEY가 없습니다.")
    sys.exit(1)

crawler = AladinAPICrawler(ttb_key=ttb_key)
isbn_re = re.compile(r'97[89]\d{10}')

with engine.connect() as conn:
    # ISBN NULL인 listings에서 고유 상품명 추출
    rows = conn.execute(text(
        "SELECT DISTINCT product_name FROM listings "
        "WHERE isbn IS NULL AND product_name IS NOT NULL AND product_name != '' "
        "ORDER BY product_name"
    )).fetchall()

    unique_names = [r[0] for r in rows]
    total = len(unique_names)
    print(f'ISBN 없는 고유 상품명: {total}개')

    found = 0
    not_found = 0
    name_to_isbn = {}

    for i, name in enumerate(unique_names):
        if i % 50 == 0:
            print(f'  [{i}/{total}] found={found}, not_found={not_found}', flush=True)

        # 상품명에서 핵심 키워드 추출 (너무 긴 이름은 앞 30자만)
        search_query = name[:30].strip()
        if not search_query:
            not_found += 1
            continue

        try:
            results = crawler.search_by_keyword(search_query, max_results=3)
            matched_isbn = ""

            for item in results:
                # 제목이 비슷하면 ISBN 채택
                api_title = item.get("title", "")
                isbn = item.get("isbn", "")
                if not isbn or not isbn_re.match(isbn):
                    continue

                # 상품명에 알라딘 제목이 포함되거나, 알라딘 제목에 상품명이 포함
                if (api_title in name or name[:20] in api_title):
                    matched_isbn = isbn
                    break

            if matched_isbn:
                name_to_isbn[name] = matched_isbn
                found += 1
            else:
                not_found += 1

            time.sleep(1)  # 알라딘 API 부하 방지

        except Exception as e:
            not_found += 1

    print(f'\n알라딘 검색 완료: found={found}, not_found={not_found}')

    # DB 업데이트
    updated = 0
    skipped = 0
    for name, isbn in name_to_isbn.items():
        # 해당 상품명의 모든 listings에 ISBN 채우기 (중복 체크 포함)
        listings = conn.execute(text(
            "SELECT id, account_id FROM listings WHERE product_name = :name AND isbn IS NULL"
        ), {'name': name}).fetchall()

        for lid, aid in listings:
            dup = conn.execute(text(
                'SELECT 1 FROM listings WHERE account_id=:aid AND isbn=:isbn'
            ), {'aid': aid, 'isbn': isbn}).first()
            if dup:
                skipped += 1
            else:
                conn.execute(text('UPDATE listings SET isbn=:isbn WHERE id=:lid'), {'isbn': isbn, 'lid': lid})
                updated += 1

    conn.commit()
    print(f'DB 업데이트: {updated}개, 중복스킵: {skipped}개')

    f = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NOT NULL')).scalar()
    n = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NULL')).scalar()
    print(f'최종: ISBN있음={f}, NULL={n}')
