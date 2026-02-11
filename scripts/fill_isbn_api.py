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
    """상품 상세에서 모든 ISBN 추출 (세트 상품 지원)"""
    data = detail.get("data", {})
    if not isinstance(data, dict):
        return ""

    isbn_set = set()  # 중복 제거용
    items = data.get("items", [])

    for item in items:
        # barcode, externalVendorSku에서 ISBN 추출
        for field in ["barcode", "externalVendorSku"]:
            val = str(item.get(field, ""))
            m = isbn_re.search(val)
            if m:
                isbn_set.add(m.group())

        # searchTags에서 ISBN 추출
        for tag in (item.get("searchTags") or []):
            m = isbn_re.search(str(tag))
            if m:
                isbn_set.add(m.group())

    # 쉼표로 구분하여 반환
    return ",".join(sorted(isbn_set)) if isbn_set else ""


with engine.connect() as conn:
    # 007-book 계정만 처리
    accounts = conn.execute(text(
        "SELECT id, vendor_id, wing_access_key, wing_secret_key "
        "FROM accounts WHERE is_active=true AND wing_api_enabled=true AND account_name='007-book'"
    )).fetchall()

    if not accounts:
        print('007-book 계정을 찾을 수 없습니다. 전체 계정으로 처리합니다.')
        accounts = conn.execute(text(
            "SELECT id, vendor_id, wing_access_key, wing_secret_key "
            "FROM accounts WHERE is_active=true AND wing_api_enabled=true"
        )).fetchall()

    clients = {}
    for a in accounts:
        clients[a[0]] = CoupangWingClient(a[1], a[2], a[3])

    rows = conn.execute(text(
        "SELECT id, account_id, coupang_product_id FROM listings "
        "WHERE isbn IS NULL AND coupang_product_id IS NOT NULL AND coupang_product_id != '' "
        "AND account_id = 1 "  # 007-book만
        "ORDER BY account_id LIMIT 10"  # 테스트로 10개만
    )).fetchall()

    total = len(rows)
    print(f'\n=== 007-book 계정 ISBN 채우기 ===')
    print(f'활성 계정: {len(accounts)}개')
    print(f'처리 대상: {total}개 (ISBN이 NULL인 listings)')
    print(f'세트 상품의 경우 쉼표로 구분된 여러 ISBN 저장\n')
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
                if failed <= 3:  # 처음 3개 실패만 출력
                    print(f'  [실패 {failed}] product_id={cpid}: ISBN 추출 실패')
        except Exception as e:
            failed += 1
            if failed <= 3:  # 처음 3개 에러만 출력
                print(f'  [에러 {failed}] product_id={cpid}: {str(e)[:100]}')

    conn.commit()
    print(f'\n완료: filled={filled}, failed={failed}, skipped={skipped}')

    f = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NOT NULL')).scalar()
    n = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NULL')).scalar()
    print(f'최종: ISBN있음={f}, NULL={n}')
