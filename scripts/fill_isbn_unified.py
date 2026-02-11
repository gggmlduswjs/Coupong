"""
통합 ISBN 채우기 스크립트
========================
전체 계정 대상, 메인 DB 사용, 3단계 패스:
  Pass 1: WING API 상품 조회 → barcode/searchTags에서 ISBN 추출
  Pass 2: books 테이블 상품명 매칭
  Pass 3: 알라딘 API 검색

사용법:
    python scripts/fill_isbn_unified.py
    python scripts/fill_isbn_unified.py --account 007-book
    python scripts/fill_isbn_unified.py --pass 2          # books 매칭만
    python scripts/fill_isbn_unified.py --limit 100       # 최대 100건
"""
import sys
import os
import re
import time
import argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.database import engine
from app.api.coupang_wing_client import CoupangWingClient

isbn_re = re.compile(r'97[89]\d{10}')


# ─── Pass 1: WING API ───

def extract_isbn_from_detail(detail):
    """WING API 상품 상세에서 모든 ISBN 추출 (세트 상품 지원)"""
    data = detail.get("data", {})
    if not isinstance(data, dict):
        return ""
    isbn_set = set()
    for item in data.get("items", []):
        for field in ["barcode", "externalVendorSku"]:
            m = isbn_re.search(str(item.get(field, "")))
            if m:
                isbn_set.add(m.group())
        for tag in (item.get("searchTags") or []):
            m = isbn_re.search(str(tag))
            if m:
                isbn_set.add(m.group())
    return ",".join(sorted(isbn_set)) if isbn_set else ""


def pass1_wing_api(account_id=None, limit=0):
    """Pass 1: WING API get_product()로 ISBN 추출"""
    print("\n=== Pass 1: WING API ISBN 추출 ===")

    with engine.connect() as conn:
        acct_filter = f"AND account_name = '{account_id}'" if account_id else ""
        accounts = conn.execute(text(f"""
            SELECT id, account_name, vendor_id, wing_access_key, wing_secret_key
            FROM accounts WHERE is_active=true AND wing_api_enabled=true {acct_filter}
        """)).fetchall()

        if not accounts:
            print("활성 WING API 계정이 없습니다.")
            return {"filled": 0, "failed": 0, "skipped": 0}

        clients = {}
        for a in accounts:
            clients[a[0]] = (a[1], CoupangWingClient(a[2], a[3], a[4]))

        limit_clause = f"LIMIT {limit}" if limit else ""
        acct_id_filter = f"AND account_id = {accounts[0][0]}" if account_id else ""
        rows = conn.execute(text(f"""
            SELECT id, account_id, coupang_product_id FROM listings
            WHERE isbn IS NULL AND coupang_product_id IS NOT NULL
            {acct_id_filter}
            ORDER BY account_id {limit_clause}
        """)).fetchall()

        total = len(rows)
        print(f"처리 대상: {total}건 (계정: {len(accounts)}개)")

        filled = failed = skipped = 0
        for i, (lid, aid, cpid) in enumerate(rows):
            if i % 50 == 0 and i > 0:
                print(f"  [{i}/{total}] filled={filled}, failed={failed}", flush=True)

            acct_name, client = clients.get(aid, ("?", None))
            if not client:
                skipped += 1
                continue

            try:
                detail = client.get_product(int(cpid))
                isbn_str = extract_isbn_from_detail(detail)
                if isbn_str:
                    dup = conn.execute(text(
                        'SELECT 1 FROM listings WHERE account_id=:aid AND isbn=:isbn'
                    ), {'aid': aid, 'isbn': isbn_str}).first()
                    if dup:
                        skipped += 1
                    else:
                        conn.execute(text(
                            'UPDATE listings SET isbn=:isbn WHERE id=:lid'
                        ), {'isbn': isbn_str, 'lid': lid})
                        filled += 1
                        if filled <= 5:
                            print(f"  [성공] [{acct_name}] product_id={cpid} → {isbn_str}")
                        if filled % 50 == 0:
                            conn.commit()
                else:
                    failed += 1
                time.sleep(0.1)  # WING API rate limit
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"  [에러] product_id={cpid}: {str(e)[:80]}")

        conn.commit()

    result = {"filled": filled, "failed": failed, "skipped": skipped}
    print(f"Pass 1 완료: {result}")
    return result


# ─── Pass 2: books 테이블 매칭 ───

def pass2_books_table(account_id=None, limit=0):
    """Pass 2: product_name → books.title 매칭으로 ISBN 추출"""
    print("\n=== Pass 2: books 테이블 매칭 ===")

    with engine.connect() as conn:
        acct_filter = ""
        if account_id:
            acct_row = conn.execute(text(
                "SELECT id FROM accounts WHERE account_name = :name"
            ), {"name": account_id}).first()
            if acct_row:
                acct_filter = f"AND account_id = {acct_row[0]}"

        limit_clause = f"LIMIT {limit}" if limit else ""
        rows = conn.execute(text(f"""
            SELECT id, account_id, product_name FROM listings
            WHERE isbn IS NULL AND product_name IS NOT NULL AND product_name != ''
            {acct_filter}
            ORDER BY id {limit_clause}
        """)).fetchall()

        total = len(rows)
        print(f"처리 대상: {total}건")

        filled = failed = skipped = 0
        for i, (lid, aid, pname) in enumerate(rows):
            if i % 100 == 0 and i > 0:
                print(f"  [{i}/{total}] filled={filled}, failed={failed}", flush=True)

            # 키워드 추출
            clean = re.sub(r'\([^)]*\)', '', pname)
            clean = re.sub(r'\d{4}년?', '', clean)
            clean = re.sub(r'세트\d*', '', clean)
            clean = re.sub(r'\s*[+&]\s*', ' ', clean)
            clean = ' '.join(clean.split()).lower().strip()

            if len(clean) < 5:
                failed += 1
                continue

            # books 테이블에서 매칭 (키워드 처음 40자)
            keyword = clean[:40]
            matches = conn.execute(text("""
                SELECT DISTINCT isbn FROM books
                WHERE LOWER(title) LIKE :kw AND isbn IS NOT NULL
                LIMIT 3
            """), {"kw": f"%{keyword}%"}).fetchall()

            if matches:
                isbn_str = ",".join([m[0] for m in matches])
                dup = conn.execute(text(
                    'SELECT 1 FROM listings WHERE account_id=:aid AND isbn=:isbn'
                ), {'aid': aid, 'isbn': isbn_str}).first()
                if dup:
                    skipped += 1
                else:
                    conn.execute(text(
                        'UPDATE listings SET isbn=:isbn WHERE id=:lid'
                    ), {'isbn': isbn_str, 'lid': lid})
                    filled += 1
                    if filled <= 5:
                        print(f"  [성공] {pname[:40]}... → {isbn_str}")
                    if filled % 50 == 0:
                        conn.commit()
            else:
                failed += 1

        conn.commit()

    result = {"filled": filled, "failed": failed, "skipped": skipped}
    print(f"Pass 2 완료: {result}")
    return result


# ─── Pass 3: 알라딘 API ───

def pass3_aladin_api(account_id=None, limit=0):
    """Pass 3: 알라딘 API 검색으로 ISBN 추출"""
    print("\n=== Pass 3: 알라딘 API 검색 ===")

    ttb_key = os.getenv('ALADIN_TTB_KEY')
    if not ttb_key:
        print("ALADIN_TTB_KEY 환경변수가 없습니다. Pass 3 건너뜁니다.")
        return {"filled": 0, "failed": 0, "skipped": 0}

    from crawlers.aladin_api_crawler import AladinAPICrawler
    crawler = AladinAPICrawler(ttb_key)

    with engine.connect() as conn:
        acct_filter = ""
        if account_id:
            acct_row = conn.execute(text(
                "SELECT id FROM accounts WHERE account_name = :name"
            ), {"name": account_id}).first()
            if acct_row:
                acct_filter = f"AND account_id = {acct_row[0]}"

        limit_clause = f"LIMIT {limit}" if limit else ""
        rows = conn.execute(text(f"""
            SELECT id, account_id, product_name FROM listings
            WHERE isbn IS NULL AND product_name IS NOT NULL AND product_name != ''
            {acct_filter}
            ORDER BY id {limit_clause}
        """)).fetchall()

        total = len(rows)
        print(f"처리 대상: {total}건 (1초/건, 예상 {total}초)")

        # 검색 키워드 정리
        remove_words = ['사은품', '선물', '증정', '포함', '무료배송']

        def clean_for_search(name):
            t = re.sub(r'\([^)]*\)', '', name)
            t = re.sub(r'\d{4}년?', '', t)
            t = re.sub(r'세트\d*', '', t)
            t = re.sub(r'전\s*\d+권', '', t)
            t = re.sub(r'\s*[+&]\s*', ' ', t)
            for w in remove_words:
                t = t.replace(w, '')
            words = ' '.join(t.split())[:50].split()[:5]
            return ' '.join(words).strip()

        filled = failed = skipped = 0
        for i, (lid, aid, pname) in enumerate(rows):
            if i % 20 == 0 and i > 0:
                print(f"  [{i}/{total}] filled={filled}, failed={failed}", flush=True)

            keyword = clean_for_search(pname)
            if not keyword or len(keyword) < 3:
                failed += 1
                continue

            try:
                results = crawler.search_by_keyword(keyword=keyword, max_results=3, sort="Accuracy")
                isbns = [r.get('isbn13') or r.get('isbn') for r in (results or []) if r.get('isbn13') or r.get('isbn')]

                if isbns:
                    isbn_str = ",".join(isbns[:3])
                    dup = conn.execute(text(
                        'SELECT 1 FROM listings WHERE account_id=:aid AND isbn=:isbn'
                    ), {'aid': aid, 'isbn': isbn_str}).first()
                    if dup:
                        skipped += 1
                    else:
                        conn.execute(text(
                            'UPDATE listings SET isbn=:isbn WHERE id=:lid'
                        ), {'isbn': isbn_str, 'lid': lid})
                        filled += 1
                        if filled <= 5:
                            print(f"  [성공] {pname[:40]}... → {isbn_str}")
                        if filled % 50 == 0:
                            conn.commit()
                else:
                    failed += 1

                time.sleep(1.0)  # 알라딘 API 1초 제한
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"  [에러] {pname[:30]}: {str(e)[:80]}")

        conn.commit()

    result = {"filled": filled, "failed": failed, "skipped": skipped}
    print(f"Pass 3 완료: {result}")
    return result


# ─── 통계 ───

def print_coverage():
    """계정별 ISBN 커버리지 출력"""
    with engine.connect() as conn:
        stats = conn.execute(text("""
            SELECT a.account_name,
                   COUNT(*) as total,
                   SUM(CASE WHEN l.isbn IS NOT NULL THEN 1 ELSE 0 END) as has_isbn
            FROM listings l
            JOIN accounts a ON l.account_id = a.id
            WHERE a.is_active = true
            GROUP BY a.account_name
        """)).fetchall()

    print("\n=== ISBN 커버리지 ===")
    for name, total, has in stats:
        pct = (has / total * 100) if total > 0 else 0
        print(f"  {name}: {has}/{total} ({pct:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="통합 ISBN 채우기")
    parser.add_argument("--account", type=str, default=None, help="특정 계정만 (예: 007-book)")
    parser.add_argument("--pass", type=int, default=0, dest="pass_num", help="특정 패스만 (1/2/3, 기본: 전부)")
    parser.add_argument("--limit", type=int, default=0, help="최대 처리 건수 (기본: 무제한)")
    args = parser.parse_args()

    print("=== 통합 ISBN 채우기 시작 ===")
    print_coverage()

    total = {"filled": 0, "failed": 0, "skipped": 0}

    passes = [args.pass_num] if args.pass_num else [1, 2, 3]

    for p in passes:
        if p == 1:
            r = pass1_wing_api(args.account, args.limit)
        elif p == 2:
            r = pass2_books_table(args.account, args.limit)
        elif p == 3:
            r = pass3_aladin_api(args.account, args.limit)
        else:
            continue
        for k in total:
            total[k] += r[k]

    print(f"\n=== 전체 결과: {total} ===")
    print_coverage()


if __name__ == "__main__":
    main()
