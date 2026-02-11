"""알라딘 API로 빠르게 ISBN 채우기"""
import sys
import io
import os
import re
import time
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from crawlers.aladin_api_crawler import AladinAPICrawler
from app.database import engine

TTB_KEY = os.getenv('ALADIN_TTB_KEY')
crawler = AladinAPICrawler(TTB_KEY)

limit = int(sys.argv[1]) if len(sys.argv) > 1 else 1000

with engine.connect() as conn:
    # ISBN 없는 상품 조회
    candidates = conn.execute(text("""
        SELECT id, account_id, product_name
        FROM listings
        WHERE (isbn IS NULL OR isbn = '')
        AND product_name IS NOT NULL
        LIMIT :limit
    """), {'limit': limit}).fetchall()

    print(f"처리 대상: {len(candidates)}개")
    print()

    success = 0
    duplicate = 0

    for idx, (listing_id, account_id, product_name) in enumerate(candidates, 1):
        # 상품명 정제
        clean = re.sub(r'\([^)]*\)', '', product_name)
        clean = re.sub(r'\+사은품|\+선물|사은품|선물|증정', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()

        try:
            results = crawler.search_by_keyword(keyword=clean, max_results=1)

            if results:
                isbn = results[0].get('isbn13') or results[0].get('isbn')

                if isbn:
                    # 중복 체크
                    dup_count = conn.execute(text("""
                        SELECT COUNT(*) FROM listings
                        WHERE account_id = :aid AND isbn = :isbn AND id != :lid
                    """), {'aid': account_id, 'isbn': isbn, 'lid': listing_id}).scalar()

                    if dup_count > 0:
                        duplicate += 1
                    else:
                        conn.execute(text("UPDATE listings SET isbn = :isbn WHERE id = :lid"),
                                     {'isbn': isbn, 'lid': listing_id})
                        success += 1

                        if success <= 10:
                            print(f"✓ [{success}] {product_name[:50]}")
                            print(f"   → {isbn}")
        except:
            pass

        if idx % 100 == 0:
            conn.commit()
            print(f"진행: {idx}/{len(candidates)} - 성공: {success}, 중복: {duplicate}")

        time.sleep(0.5)

    conn.commit()

    print()
    print(f"완료: 성공 {success}개, 중복 {duplicate}개")
