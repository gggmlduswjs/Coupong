#!/usr/bin/env python3
"""
교보문고 스마트 크롤링 - 중복 제거 및 결과 공유

1. 유니크한 상품명만 크롤링 (중복 제거)
2. 찾은 ISBN을 상품명 기반으로 모든 계정에 적용

사용법:
  python scripts/fill_isbn_kyobo_smart.py [--limit N] [--delay S]
"""

import re
import sys
import time
import argparse
from pathlib import Path
from urllib.parse import quote
import io
from collections import defaultdict

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


def normalize_product_name(name: str) -> str:
    """상품명 정규화 (매칭용)"""
    s = name.lower().strip()
    for pat, repl in NOISE_PATTERNS:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


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
    return s[:50]


def search_kyobo(keyword: str) -> list[str]:
    """교보 검색 → 상품 상세 ID 목록 반환"""
    url = f"{KYOBO_SEARCH}?keyword={quote(keyword)}&target=total"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        html = r.text
        ids = re.findall(r"product\.kyobobook\.co\.kr/detail/(S\d+)", html)
        if not ids:
            ids = re.findall(r"/detail/(S\d+)", html)
        return list(dict.fromkeys(ids))[:3]
    except:
        return []


def fetch_isbn_from_detail(prod_id: str) -> str | None:
    """상세페이지에서 ISBN 추출"""
    url = f"{KYOBO_DETAIL}/{prod_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        r.raise_for_status()
        html = r.content.decode(r.encoding or "utf-8", errors="replace")

        # 여러 패턴 시도
        patterns = [
            r"\|\s*ISBN\s*\|\s*(\d{13})\s*\|",
            r"ISBN[\s:]*(\d{13})",
            r"/pdt/(97[89]\d{10})\.",
            r"(97[89]\d{10})",
        ]

        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                return m.group(1)
    except:
        pass
    return None


def get_unique_products(limit: int = 0):
    """유니크한 상품명만 조회 (중복 제거)"""
    conn = engine.connect()

    # ISBN 없는 모든 상품 조회
    query = text("""
        SELECT id, account_id, product_name
        FROM listings
        WHERE (isbn IS NULL OR isbn = '')
        AND product_name IS NOT NULL
        AND product_name != ''
        ORDER BY id
    """)

    all_products = conn.execute(query).fetchall()
    conn.close()

    # 상품명으로 그룹화 (정규화된 이름 기준)
    by_normalized_name = defaultdict(list)
    for listing_id, account_id, product_name in all_products:
        normalized = normalize_product_name(product_name)
        if len(normalized) >= 6:
            by_normalized_name[normalized].append({
                'id': listing_id,
                'account_id': account_id,
                'product_name': product_name,
                'normalized': normalized
            })

    # 각 그룹에서 대표 상품 1개씩만 선택
    unique_products = []
    for normalized, group in by_normalized_name.items():
        # 첫 번째 상품을 대표로 선택
        unique_products.append({
            'representative': group[0],
            'group_size': len(group),
            'all_items': group
        })

    if limit > 0:
        unique_products = unique_products[:limit]

    print(f"전체 상품: {len(all_products):,}개")
    print(f"유니크 상품명: {len(unique_products):,}개 (중복 제거)")
    print()

    return unique_products


def update_all_accounts(normalized_name: str, isbn: str, all_items: list) -> dict:
    """찾은 ISBN을 해당 상품명의 모든 계정에 업데이트"""
    conn = engine.connect()

    stats = {'success': 0, 'duplicate': 0, 'error': 0}

    for item in all_items:
        try:
            update_query = text("UPDATE listings SET isbn = :isbn WHERE id = :lid")
            conn.execute(update_query, {'isbn': isbn, 'lid': item['id']})
            stats['success'] += 1
        except Exception as e:
            stats['error'] += 1

    conn.commit()
    conn.close()
    return stats


def main():
    parser = argparse.ArgumentParser(description="교보문고 스마트 크롤링 (중복 제거)")
    parser.add_argument("--limit", type=int, default=0, help="처리 상품 수 (0=전체)")
    parser.add_argument("--delay", type=float, default=1.5, help="요청 간 대기(초)")
    args = parser.parse_args()

    print("=" * 80)
    print("교보문고 스마트 크롤링 (중복 제거 + 결과 공유)")
    print("=" * 80)
    print()

    unique_products = get_unique_products(args.limit)

    total_stats = {
        'crawled': 0,
        'found': 0,
        'not_found': 0,
        'total_updated': 0,
        'total_duplicate': 0,
    }

    for i, item in enumerate(unique_products, 1):
        rep = item['representative']
        group_size = item['group_size']

        search_query = clean_for_search(rep['product_name'])

        if len(search_query) < 6:
            print(f"[{i}/{len(unique_products)}] ⏭️  너무 짧음 (그룹: {group_size}개)")
            total_stats['not_found'] += 1
            continue

        print(f"[{i}/{len(unique_products)}] {search_query[:50]}... (그룹: {group_size}개)")

        # 교보문고 검색
        prod_ids = search_kyobo(search_query)
        time.sleep(args.delay)

        if not prod_ids:
            print(f"    → ❌ 검색 결과 없음")
            total_stats['not_found'] += 1
            continue

        # 상세 페이지에서 ISBN 추출
        found_isbn = None
        for pid in prod_ids:
            isbn = fetch_isbn_from_detail(pid)
            time.sleep(args.delay)
            if isbn:
                found_isbn = isbn
                break

        if not found_isbn:
            print(f"    → ❌ ISBN 없음")
            total_stats['not_found'] += 1
            continue

        total_stats['crawled'] += 1
        total_stats['found'] += 1

        # 모든 계정에 업데이트
        update_stats = update_all_accounts(rep['normalized'], found_isbn, item['all_items'])
        total_stats['total_updated'] += update_stats['success']
        total_stats['total_duplicate'] += update_stats['duplicate']

        print(f"    → ✅ ISBN {found_isbn}")
        print(f"       업데이트: {update_stats['success']}개, 중복: {update_stats['duplicate']}개")

        # 100개마다 통계
        if i % 100 == 0:
            print()
            print(f"진행: {i}/{len(unique_products)} - 발견: {total_stats['found']}, 업데이트: {total_stats['total_updated']}")
            print()

    print()
    print("=" * 80)
    print("완료")
    print("=" * 80)
    print(f"크롤링 대상: {len(unique_products):,}개 (유니크)")
    print(f"✅ ISBN 발견: {total_stats['found']:,}개")
    print(f"📝 총 업데이트: {total_stats['total_updated']:,}개")
    print(f"⚠️  중복: {total_stats['total_duplicate']:,}개")
    print(f"❌ 실패: {total_stats['not_found']:,}개")
    print("=" * 80)


if __name__ == "__main__":
    main()
