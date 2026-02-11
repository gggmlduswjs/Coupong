#!/usr/bin/env python3
"""
교보문고 검색 크롤링으로 DB의 ISBN 채우기

DB에서 ISBN 없는 상품을 조회하고,
교보문고 검색 → 첫 검색결과 상세페이지 → ISBN 추출 → DB 업데이트

사용법:
  python scripts/fill_isbn_kyobo_from_db.py [--limit N] [--delay S]
  --limit N : 처리할 상품 수 (기본 100, 0=전체)
  --delay S : 요청 간 대기 초 (기본 2.0, rate limit 회피)
  --dry-run : 테스트 모드 (DB 업데이트 안 함)
"""

import re
import sys
import time
import argparse
from pathlib import Path
from urllib.parse import quote
import io

# 프로젝트 루트 경로 추가
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Windows cp949 인코딩 대응
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

try:
    import requests
except ImportError:
    print("❌ pip install requests 필요")
    sys.exit(1)

from sqlalchemy import text
from app.database import engine

KYOBO_SEARCH = "https://search.kyobobook.co.kr/search"
KYOBO_DETAIL = "https://product.kyobobook.co.kr/detail"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://search.kyobobook.co.kr/",
}

# 상품명 정제 패턴
NOISE_PATTERNS = [
    (r"\+\s*사은품", ""),
    (r"\+\s*선물", ""),
    (r"사은품\s*증정\)?", ""),
    (r"선물\s*\+", ""),
    (r"\(\s*선물\s*\)", ""),
    (r"\(\s*사은품증정\s*\)", ""),
    (r"사은품\s*\+", ""),
    (r"\*+", ""),
    (r"\#\w+", ""),
    (r"\([^)]*\)", ""),  # 모든 괄호 제거
]


def clean_for_search(name: str) -> str:
    """검색용 상품명 정제"""
    s = name.strip()
    for pat, repl in NOISE_PATTERNS:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    # 세트 상품은 첫 번째 항목만
    if "+" in s or "&" in s or "세트" in s:
        parts = re.split(r"\s*[+&]\s*", s)
        s = parts[0].replace("세트", "").strip()
    return s[:50]  # 50자로 제한


def search_kyobo(keyword: str, verbose: bool = False) -> list[str]:
    """교보 검색 → 상품 상세 ID 목록 반환"""
    url = f"{KYOBO_SEARCH}?keyword={quote(keyword)}&target=total"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        html = r.text
        # product.kyobobook.co.kr/detail/S000219239001 형태 링크 추출
        ids = re.findall(r"product\.kyobobook\.co\.kr/detail/(S\d+)", html)
        if not ids:
            ids = re.findall(r"/detail/(S\d+)", html)
        result = list(dict.fromkeys(ids))[:3]  # 상위 3개만
        if verbose and not result:
            print(f"      [디버그] 검색 0건")
        return result
    except Exception as e:
        if verbose:
            print(f"      [검색 오류] {e}")
        return []


def fetch_isbn_from_detail(prod_id: str, verbose: bool = False) -> str | None:
    """상세페이지에서 ISBN 추출"""
    url = f"{KYOBO_DETAIL}/{prod_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        r.raise_for_status()
        html = r.content.decode(r.encoding or "utf-8", errors="replace")

        # 패턴 1: | ISBN | 9791173166860 |
        m = re.search(r"\|\s*ISBN\s*\|\s*(\d{13})\s*\|", html)
        if m:
            return m.group(1)

        # 패턴 2: ISBN: 9791173166860
        m = re.search(r"ISBN[\s:]*(\d{13})", html, re.I)
        if m:
            return m.group(1)

        # 패턴 3: 이미지 URL에서 추출
        m = re.search(r"/pdt/(97[89]\d{10})\.", html)
        if m:
            return m.group(1)

        # 패턴 4: 일반적인 ISBN 13자리
        m = re.search(r"(97[89]\d{10})", html)
        if m:
            return m.group(1)

    except Exception as e:
        if verbose:
            print(f"      [상세 오류] {e}")
    return None


def get_missing_isbn_products(limit: int = 0):
    """DB에서 ISBN 없는 상품 조회"""
    conn = engine.connect()
    query = text("""
        SELECT id, account_id, product_name
        FROM listings
        WHERE (isbn IS NULL OR isbn = '')
        AND product_name IS NOT NULL
        AND product_name != ''
        ORDER BY id
    """)

    if limit > 0:
        query = text(str(query) + f" LIMIT {limit}")

    result = conn.execute(query).fetchall()
    conn.close()
    return result


def update_isbn(listing_id: int, isbn: str, dry_run: bool = False):
    """DB에 ISBN 업데이트"""
    if dry_run:
        return True

    try:
        conn = engine.connect()

        # 중복 체크
        check_query = text("""
            SELECT COUNT(*) FROM listings
            WHERE isbn = :isbn
            AND id != :lid
            AND account_id = (SELECT account_id FROM listings WHERE id = :lid)
        """)
        dup_count = conn.execute(check_query, {'isbn': isbn, 'lid': listing_id}).scalar()

        if dup_count > 0:
            conn.close()
            return False  # 중복

        # 업데이트
        update_query = text("UPDATE listings SET isbn = :isbn WHERE id = :lid")
        conn.execute(update_query, {'isbn': isbn, 'lid': listing_id})
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"      [DB 오류] {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="교보문고 크롤링으로 DB ISBN 채우기")
    parser.add_argument("--limit", type=int, default=100, help="처리 상품 수 (0=전체)")
    parser.add_argument("--delay", type=float, default=2.0, help="요청 간 대기(초)")
    parser.add_argument("--verbose", "-v", action="store_true", help="디버그 출력")
    parser.add_argument("--dry-run", action="store_true", help="테스트 모드 (DB 미업데이트)")
    args = parser.parse_args()

    print("=" * 80)
    print("교보문고 크롤링으로 ISBN 채우기")
    print("=" * 80)
    print(f"모드: {'DRY RUN (테스트)' if args.dry_run else 'LIVE'}")
    print(f"제한: {args.limit if args.limit > 0 else '전체'}")
    print(f"대기: {args.delay}초")
    print()

    products = get_missing_isbn_products(args.limit)
    print(f"처리 대상: {len(products):,}개")
    print()

    stats = {
        'total': len(products),
        'success': 0,
        'duplicate': 0,
        'not_found': 0,
    }

    for i, (listing_id, account_id, product_name) in enumerate(products, 1):
        search_query = clean_for_search(product_name)

        if len(search_query) < 6:
            print(f"[{i}/{len(products)}] `{listing_id}` ⏭️  너무 짧음: {product_name[:40]}")
            stats['not_found'] += 1
            continue

        print(f"[{i}/{len(products)}] `{listing_id}` {search_query[:45]}...")

        # 교보문고 검색
        prod_ids = search_kyobo(search_query, verbose=args.verbose)
        time.sleep(args.delay)

        if not prod_ids:
            print(f"    → ❌ 검색 결과 없음")
            stats['not_found'] += 1
            continue

        # 상세 페이지에서 ISBN 추출
        found_isbn = None
        for pid in prod_ids:
            isbn = fetch_isbn_from_detail(pid, verbose=args.verbose)
            time.sleep(args.delay)
            if isbn:
                found_isbn = isbn
                break

        if not found_isbn:
            print(f"    → ❌ ISBN 없음")
            stats['not_found'] += 1
            continue

        # DB 업데이트
        updated = update_isbn(listing_id, found_isbn, args.dry_run)
        if updated:
            stats['success'] += 1
            print(f"    → ✅ ISBN {found_isbn}")
        else:
            stats['duplicate'] += 1
            print(f"    → ⚠️  중복: {found_isbn}")

        # 100개마다 통계 출력
        if i % 100 == 0:
            print()
            print(f"진행: {i}/{len(products)} - 성공: {stats['success']}, 중복: {stats['duplicate']}, 실패: {stats['not_found']}")
            print()

    print()
    print("=" * 80)
    print("완료")
    print("=" * 80)
    print(f"총 처리: {stats['total']:,}개")
    print(f"✅ 성공: {stats['success']:,}개 ({stats['success']/stats['total']*100:.1f}%)")
    print(f"⚠️  중복: {stats['duplicate']:,}개")
    print(f"❌ 실패: {stats['not_found']:,}개")
    print("=" * 80)


if __name__ == "__main__":
    main()
