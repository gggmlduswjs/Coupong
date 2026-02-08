"""WING API 상세 조회로 listings에 매칭되는 books 이미지 채우기
listings 자체에는 이미지 컬럼이 없으므로,
coupang_product_id로 상세 조회 → 이미지 URL 추출 → books 테이블에 저장
(ISBN이나 제목으로 매칭되는 book이 없으면 새로 books에 INSERT)
"""
import sys
import os
import time
import re

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.api.coupang_wing_client import CoupangWingClient
from app.constants import WING_ACCOUNT_ENV_MAP
from app.database import engine
isbn_re = re.compile(r'97[89]\d{10}')


def extract_from_detail(detail):
    """상세 조회 결과에서 이미지 URL, ISBN 추출"""
    data = detail.get("data", {})
    if not isinstance(data, dict):
        return "", ""

    # 이미지
    img_url = ""
    images = data.get("images", [])
    if images:
        img_url = images[0].get("imageUrl", "") or images[0].get("cdnPath", "")

    # ISBN (items의 barcode, externalVendorSku, searchTags에서)
    isbn = ""
    items = data.get("items", [])
    for item in items:
        for field in ["barcode", "externalVendorSku"]:
            val = str(item.get(field, ""))
            m = isbn_re.search(val)
            if m:
                isbn = m.group()
                break
        if isbn:
            break
        for tag in (item.get("searchTags") or []):
            m = isbn_re.search(str(tag))
            if m:
                isbn = m.group()
                break
        if isbn:
            break

    return img_url, isbn


with engine.connect() as conn:
    # 계정별 클라이언트
    accounts = conn.execute(text(
        'SELECT id, account_name, vendor_id, wing_access_key, wing_secret_key '
        'FROM accounts WHERE is_active=1 AND wing_api_enabled=1'
    )).fetchall()

    clients = {}
    for a in accounts:
        aid, aname, vid, ak, sk = a
        if not ak:
            prefix = WING_ACCOUNT_ENV_MAP.get(aname, '')
            if prefix:
                vid = os.getenv(f'{prefix}_VENDOR_ID', vid or '')
                ak = os.getenv(f'{prefix}_ACCESS_KEY', '')
                sk = os.getenv(f'{prefix}_SECRET_KEY', '')
        if vid and ak and sk:
            clients[aid] = CoupangWingClient(vid, ak, sk)

    # 대상: books에 매칭 안 되는 listings
    rows = conn.execute(text('''
        SELECT l.id, l.account_id, l.coupang_product_id, l.isbn, l.product_name, l.sale_price, l.original_price
        FROM listings l
        WHERE l.coupang_product_id IS NOT NULL AND l.coupang_product_id != ''
        ORDER BY l.account_id
    ''')).fetchall()

    total = len(rows)
    print(f'전체 listings: {total}개')

    updated_isbn = 0
    updated_img = 0
    new_books = 0
    failed = 0
    skipped = 0

    for i, row in enumerate(rows):
        lid, aid, cpid, existing_isbn, pname, sp, op = row

        if i % 500 == 0:
            print(f'  [{i}/{total}] isbn={updated_isbn}, img={updated_img}, new_book={new_books}, failed={failed}', flush=True)

        client = clients.get(aid)
        if not client:
            skipped += 1
            continue

        try:
            detail = client.get_product(int(cpid))
            img_url, isbn = extract_from_detail(detail)

            if not img_url and not isbn:
                failed += 1
                continue

            # ISBN 업데이트 (listings)
            if isbn and not existing_isbn:
                conn.execute(text('UPDATE listings SET isbn=:isbn WHERE id=:id'), {'isbn': isbn, 'id': lid})
                updated_isbn += 1

            final_isbn = isbn or existing_isbn

            # books 테이블에 매칭되는 레코드 찾기
            book = None
            if final_isbn:
                book = conn.execute(text('SELECT id, image_url FROM books WHERE isbn=:isbn'), {'isbn': final_isbn}).first()
            if not book and pname:
                safe_name = pname.replace("'", "''")
                book = conn.execute(text(f"SELECT id, image_url FROM books WHERE title='{safe_name}'")).first()

            if book:
                # 이미지 업데이트
                bid, existing_img = book
                if img_url and not existing_img:
                    conn.execute(text('UPDATE books SET image_url=:url WHERE id=:id'), {'url': img_url, 'id': bid})
                    updated_img += 1
            else:
                # books에 없으면 새로 INSERT (이미지 포함)
                if final_isbn and img_url:
                    dup = conn.execute(text('SELECT 1 FROM books WHERE isbn=:isbn'), {'isbn': final_isbn}).first()
                    if not dup:
                        conn.execute(text('''
                            INSERT INTO books (isbn, title, list_price, image_url, is_processed, publisher_name)
                            VALUES (:isbn, :title, :price, :img, 1, '')
                        '''), {'isbn': final_isbn, 'title': pname or '', 'price': op or 0, 'img': img_url})
                        new_books += 1

            if (i + 1) % 200 == 0:
                conn.commit()

            time.sleep(0.1)  # rate limit

        except Exception as e:
            failed += 1

    conn.commit()
    print(f'\n완료: isbn업데이트={updated_isbn}, 이미지업데이트={updated_img}, 신규book={new_books}, 실패={failed}, 스킵={skipped}')

    # 최종 통계
    total_img = conn.execute(text("SELECT COUNT(*) FROM books WHERE image_url IS NOT NULL AND image_url != ''")).scalar()
    total_books = conn.execute(text("SELECT COUNT(*) FROM books")).scalar()
    print(f'books 이미지: {total_img}/{total_books}')
