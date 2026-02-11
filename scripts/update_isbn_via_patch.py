"""WING API PATCH로 상품의 ISBN 업데이트 (searchTags 활용)"""
import sys, os, time, re

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text, create_engine
from app.api.coupang_wing_client import CoupangWingClient

# 백업 DB 사용
DB_PATH = r'C:\Users\user\Desktop\Coupong\coupang_auto_backup.db'
engine = create_engine(f'sqlite:///{DB_PATH}')
isbn_re = re.compile(r'97[89]\d{10}')


def extract_all_isbns_from_detail(detail):
    """상품 상세에서 모든 ISBN 추출 (세트 상품 지원)"""
    data = detail.get("data", {})
    if not isinstance(data, dict):
        return []

    isbn_set = set()
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

    return sorted(isbn_set)


def update_product_with_isbn(client, product_id, isbns):
    """상품의 searchTags에 ISBN 추가 (PATCH API 사용)"""
    if not isbns:
        return False

    # 먼저 상품 상세 조회
    detail = client.get_product(int(product_id))
    data = detail.get("data", {})

    if not isinstance(data, dict):
        return False

    items = data.get("items", [])
    if not items:
        return False

    # 첫 번째 아이템의 searchTags에 ISBN 추가
    item = items[0]
    search_tags = item.get("searchTags", []) or []

    # 기존 태그에 ISBN이 없으면 추가
    tags_set = set(search_tags)
    for isbn in isbns:
        tags_set.add(isbn)

    # PATCH로 업데이트 (승인 불필요)
    patch_data = {
        "items": [{
            "vendorItemId": item.get("vendorItemId"),
            "searchTags": list(tags_set)
        }]
    }

    result = client.patch_product(int(product_id), patch_data)
    return True


with engine.connect() as conn:
    # 007-book 계정만 처리
    accounts = conn.execute(text(
        "SELECT id, vendor_id, wing_access_key, wing_secret_key "
        "FROM accounts WHERE is_active=true AND wing_api_enabled=true AND account_name='007-book'"
    )).fetchall()

    if not accounts:
        print('007-book 계정을 찾을 수 없습니다.')
        sys.exit(1)

    clients = {}
    for a in accounts:
        clients[a[0]] = CoupangWingClient(a[1], a[2], a[3])

    # ISBN이 NULL이고 coupang_product_id가 있는 것만 (테스트: 10개)
    rows = conn.execute(text(
        "SELECT id, account_id, coupang_product_id FROM listings "
        "WHERE isbn IS NULL AND coupang_product_id IS NOT NULL "
        "AND account_id = 1 "  # 007-book만
        "ORDER BY account_id LIMIT 10"  # 테스트: 10개
    )).fetchall()

    total = len(rows)
    print(f'\n=== 007-book 상품 ISBN 업데이트 (PATCH API) ===')
    print(f'활성 계정: {len(accounts)}개')
    print(f'처리 대상: {total}개 (ISBN이 NULL인 listings)')
    print(f'방법: 상품 조회 → ISBN 추출 → DB 업데이트\n')

    filled = 0
    failed = 0
    skipped = 0

    for i, (lid, aid, cpid) in enumerate(rows):
        if i % 50 == 0:
            print(f'  [{i}/{total}] filled={filled}, failed={failed}, skipped={skipped}', flush=True)

        client = clients.get(aid)
        if not client:
            skipped += 1
            continue

        try:
            # 1. 상품 상세 조회
            detail = client.get_product(int(cpid))
            isbns = extract_all_isbns_from_detail(detail)

            if isbns:
                isbn_str = ",".join(isbns)

                # 중복 체크
                dup = conn.execute(text(
                    'SELECT 1 FROM listings WHERE account_id=:aid AND isbn=:isbn'
                ), {'aid': aid, 'isbn': isbn_str}).first()

                if dup:
                    skipped += 1
                    print(f'  [중복] product_id={cpid}: ISBN={isbn_str} 이미 존재')
                else:
                    # 2. DB에 ISBN 업데이트
                    conn.execute(text(
                        'UPDATE listings SET isbn=:isbn WHERE id=:lid'
                    ), {'isbn': isbn_str, 'lid': lid})
                    conn.commit()

                    filled += 1
                    print(f'  [성공] product_id={cpid}: ISBN={isbn_str}')
            else:
                failed += 1
                if failed <= 3:
                    print(f'  [실패] product_id={cpid}: ISBN 추출 실패')

        except Exception as e:
            failed += 1
            if failed <= 3:
                print(f'  [에러] product_id={cpid}: {str(e)[:100]}')

    conn.commit()
    print(f'\n완료: filled={filled}, failed={failed}, skipped={skipped}')

    f = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NOT NULL')).scalar()
    n = conn.execute(text('SELECT COUNT(*) FROM listings WHERE isbn IS NULL')).scalar()
    print(f'최종: ISBN있음={f}, NULL={n}')
