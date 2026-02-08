"""WING API 상세 조회로 listings ISBN 채우기"""
import sys, os, time, re

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.api.coupang_wing_client import CoupangWingClient
from app.database import engine
isbn_re = re.compile(r'97[89]\d{10}')


def extract_isbn_from_detail(detail):
    data = detail.get("data", {})
    if not isinstance(data, dict):
        return ""
    items = data.get("items", [])
    for item in items:
        for field in ["barcode", "externalVendorSku"]:
            val = str(item.get(field, ""))
            m = isbn_re.search(val)
            if m:
                return m.group()
        for tag in (item.get("searchTags") or []):
            m = isbn_re.search(str(tag))
            if m:
                return m.group()
    return ""


with engine.connect() as conn:
    accounts = conn.execute(text(
        'SELECT id, vendor_id, wing_access_key, wing_secret_key '
        'FROM accounts WHERE is_active=1 AND wing_api_enabled=1'
    )).fetchall()

    clients = {}
    for a in accounts:
        clients[a[0]] = CoupangWingClient(a[1], a[2], a[3])

    rows = conn.execute(text(
        "SELECT id, account_id, coupang_product_id FROM listings "
        "WHERE isbn IS NULL AND coupang_product_id IS NOT NULL AND coupang_product_id != '' "
        "ORDER BY account_id"
    )).fetchall()

    total = len(rows)
    print(f'처리 대상: {total}개')
    filled = 0
    failed = 0
    skipped = 0

    for i, (lid, aid, cpid) in enumerate(rows):
        if i % 200 == 0:
            print(f'  [{i}/{total}] filled={filled}, failed={failed}, skipped={skipped}', flush=True)

        client = clients.get(aid)
        if not client:
            skipped += 1
            continue

        try:
            detail = client.get_product(int(cpid))
            isbn = extract_isbn_from_detail(detail)
            if isbn:
                dup = conn.execute(text(
                    'SELECT 1 FROM listings WHERE account_id=:aid AND isbn=:isbn'
                ), {'aid': aid, 'isbn': isbn}).first()
                if dup:
                    skipped += 1
                else:
                    conn.execute(text('UPDATE listings SET isbn=:isbn WHERE id=:lid'), {'isbn': isbn, 'lid': lid})
                    filled += 1
                    if filled % 50 == 0:
                        conn.commit()
            else:
                failed += 1
        except Exception as e:
            failed += 1

    conn.commit()
    print(f'\n완료: filled={filled}, failed={failed}, skipped={skipped}')

    f = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NOT NULL')).scalar()
    n = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NULL')).scalar()
    print(f'최종: ISBN있음={f}, NULL={n}')
