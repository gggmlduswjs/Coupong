"""
Phase 2: 묶음 상품 분리 처리 스크립트

묶음 상품 패턴을 감지하고 각 구성품마다 ISBN을 검색합니다.
- "A + B", "A & B", "세트" 패턴 감지
- 각 구성품마다 워터폴 검색: Books 테이블 → 알라딘 API
- 선물/사은품 제외
- 쉼표로 구분하여 저장

예상 성과: +400~600 ISBN (15-20분)
"""
import re
import json
import sys
import io
import os
import time
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

# UTF-8 출력 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

import sqlite3
from crawlers.aladin_api_crawler import AladinAPICrawler


def detect_bundle(product_name: str) -> Optional[List[str]]:
    """
    묶음 상품 패턴 감지 및 구성품 분리

    감지 패턴:
    - "A + B", "A+B"
    - "A & B", "A&B"
    - "세트", "전 N권"

    Returns:
        구성품 리스트 또는 None (단일 상품)
    """
    if not product_name:
        return None

    # 세트 키워드 확인
    has_bundle_keyword = bool(re.search(r'세트|전\s*\d+권', product_name))

    # + 또는 & 구분자 확인
    has_separator = bool(re.search(r'\s*[+&]\s*', product_name))

    if not (has_bundle_keyword or has_separator):
        return None

    # 구분자로 분리
    components = re.split(r'\s*[+&]\s*', product_name)

    if len(components) < 2:
        return None

    # 선물/사은품 제외
    filtered = []
    for comp in components:
        # 선물, 사은품, 증정 키워드 포함 여부
        if any(kw in comp for kw in ['선물', '사은품', '증정', '포함', '무료']):
            continue

        # 너무 짧으면 제외 (단순 구분자 오류)
        if len(comp.strip()) < 3:
            continue

        filtered.append(comp.strip())

    # 유효한 구성품이 2개 이상일 때만 묶음으로 처리
    if len(filtered) >= 2:
        return filtered

    return None


def extract_keywords_for_search(component: str) -> Tuple[str, str]:
    """
    구성품명에서 검색용 키워드와 퍼블리셔 추출

    Returns:
        (keywords, publisher)
    """
    # 괄호 안의 출판사/저자 정보 추출
    publisher_match = re.search(r'\[(.*?)\]', component)
    if not publisher_match:
        publisher_match = re.search(r'\((.*?)\)', component)

    publisher = publisher_match.group(1) if publisher_match else ""

    # 괄호 제거
    clean_name = re.sub(r'\[.*?\]', '', component)
    clean_name = re.sub(r'\(.*?\)', '', clean_name)

    # 연도 제거
    clean_name = re.sub(r'\d{4}년?', '', clean_name)
    clean_name = re.sub(r'20\d{2}', '', clean_name)

    # 권수 제거
    clean_name = re.sub(r'\d+권', '', clean_name)

    # 세트 제거
    clean_name = re.sub(r'세트\d*', '', clean_name)

    # 공백 정리
    clean_name = ' '.join(clean_name.split())

    return clean_name.strip(), publisher.strip()


def search_isbn_from_books(component: str, conn) -> Optional[str]:
    """
    Books 테이블에서 ISBN 검색 (즉시)

    Returns:
        ISBN 또는 None
    """
    keywords, publisher = extract_keywords_for_search(component)

    # 너무 짧으면 스킵
    if len(keywords) < 3:
        return None

    try:
        cursor = conn.cursor()

        # 1단계: 키워드 + 퍼블리셔 매칭
        if publisher:
            cursor.execute("""
                SELECT DISTINCT b.isbn
                FROM books b
                LEFT JOIN publishers pub ON b.publisher_id = pub.id
                WHERE LOWER(b.title) LIKE ? AND LOWER(pub.name) LIKE ?
                LIMIT 1
            """, (f'%{keywords.lower()[:40]}%', f'%{publisher.lower()}%'))

            row = cursor.fetchone()
            if row:
                return row[0]

        # 2단계: 키워드만 매칭
        cursor.execute("""
            SELECT DISTINCT isbn
            FROM books
            WHERE LOWER(title) LIKE ?
            LIMIT 1
        """, (f'%{keywords.lower()[:40]}%',))

        row = cursor.fetchone()
        if row:
            return row[0]

    except Exception as e:
        print(f"      [Books 테이블 검색 에러] {str(e)[:50]}")

    return None


def search_isbn_from_aladin(component: str, crawler: AladinAPICrawler) -> Optional[str]:
    """
    알라딘 API에서 ISBN 검색 (1초 대기)

    Returns:
        ISBN 또는 None
    """
    keywords, publisher = extract_keywords_for_search(component)

    # 너무 짧으면 스킵
    if len(keywords) < 3:
        return None

    try:
        # 검색 키워드 준비 (앞 5단어)
        search_words = ' '.join(keywords.split()[:5])

        # 알라딘 API 검색
        results = crawler.search_by_keyword(
            keyword=search_words,
            max_results=3,
            sort="Accuracy"
        )

        if not results:
            return None

        # 퍼블리셔 필터링
        if publisher:
            for item in results:
                item_pub = item.get('publisher', '')
                if publisher.lower() in item_pub.lower():
                    isbn = item.get('isbn13') or item.get('isbn')
                    if isbn:
                        return isbn

        # 퍼블리셔 매칭 실패 시 첫 번째 결과 사용
        isbn = results[0].get('isbn13') or results[0].get('isbn')
        return isbn

    except Exception as e:
        print(f"      [알라딘 API 에러] {str(e)[:50]}")

    return None


def process_bundle(product_name: str, conn, crawler: AladinAPICrawler, verbose: bool = False) -> Optional[str]:
    """
    묶음 상품을 처리하여 모든 구성품의 ISBN 추출

    Returns:
        쉼표로 구분된 ISBN 문자열 또는 None
    """
    components = detect_bundle(product_name)

    if not components:
        return None

    if verbose:
        print(f"   묶음 감지: {len(components)}개 구성품")
        for i, comp in enumerate(components, 1):
            print(f"      [{i}] {comp[:60]}")

    isbns = []

    for i, comp in enumerate(components, 1):
        if verbose:
            print(f"      [{i}/{len(components)}] 검색 중...", end=' ')

        # Books 테이블 검색 (즉시, 알라딘 API는 세트 상품명으로 검색 시 결과 없음)
        isbn = search_isbn_from_books(comp, conn)

        if isbn:
            if verbose:
                print(f"✓ Books 테이블에서 발견: {isbn}")
            isbns.append(isbn)
        else:
            if verbose:
                print("✗ 발견 못함")

    if isbns:
        return ','.join(isbns)

    return None


def detect_and_split_bundles(dry_run: bool = False, limit: int = None, db_path: str = None, verbose: bool = False):
    """
    묶음 상품을 감지하고 각 구성품의 ISBN을 검색하여 업데이트

    Args:
        dry_run: True일 경우 변경사항을 커밋하지 않고 미리보기만
        limit: 처리할 최대 레코드 수 (테스트용)
        db_path: 사용할 DB 파일 경로
        verbose: 상세 로그 출력
    """
    # 알라딘 API 초기화
    TTB_KEY = os.getenv('ALADIN_TTB_KEY')
    if not TTB_KEY:
        print('❌ ALADIN_TTB_KEY 환경변수가 필요합니다.')
        sys.exit(1)

    crawler = AladinAPICrawler(TTB_KEY)

    # DB 연결
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=" * 80)
    print("Phase 2: 묶음 상품 분리 처리")
    print("=" * 80)
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모드: {'DRY RUN (미리보기)' if dry_run else 'LIVE (실제 업데이트)'}")
    if limit:
        print(f"제한: 최대 {limit}개 레코드")
    print()

    # ISBN이 없고 묶음 패턴이 있는 listings 조회
    query = """
        SELECT id, product_name
        FROM listings
        WHERE (isbn IS NULL OR isbn = '')
          AND product_name IS NOT NULL
          AND product_name != ''
          AND (
              product_name LIKE '%+%'
              OR product_name LIKE '%&%'
              OR product_name LIKE '%세트%'
              OR product_name LIKE '%전%권%'
          )
    """

    if limit:
        query += f" LIMIT {limit}"

    cursor = conn.cursor()
    cursor.execute(query)
    candidates = cursor.fetchall()

    print(f"📦 대상 레코드: {len(candidates):,}개 (묶음 패턴 포함)")
    print()

    # 통계
    stats = {
        'total': len(candidates),
        'bundle_detected': 0,
        'isbn_found': 0,
        'isbn_not_found': 0,
        'not_bundle': 0
    }

    updated_listings = []

    for idx, row in enumerate(candidates, 1):
        listing_id = row[0]
        product_name = row[1]

        if verbose or (idx <= 5):  # 처음 5개는 항상 출력
            print(f"[{idx}/{len(candidates)}] ID {listing_id}: {product_name[:70]}")

        # 묶음 처리
        isbn_str = process_bundle(product_name, conn, crawler, verbose=(verbose or idx <= 5))

        if isbn_str:
            stats['bundle_detected'] += 1
            stats['isbn_found'] += 1
            updated_listings.append((listing_id, isbn_str, product_name))

            if not verbose and idx > 5:
                # 진행 상황 간단히 표시 (10개마다)
                if idx % 10 == 0:
                    print(f"✓ 진행: {idx:,}/{len(candidates):,} ({idx/len(candidates)*100:.1f}%) - 성공: {stats['isbn_found']:,}")
        else:
            # 묶음 패턴은 있지만 ISBN을 찾지 못함
            components = detect_bundle(product_name)
            if components:
                stats['bundle_detected'] += 1
                stats['isbn_not_found'] += 1
            else:
                stats['not_bundle'] += 1

    print()
    print("=" * 80)
    print("처리 결과")
    print("=" * 80)
    print(f"총 처리: {stats['total']:,}개")
    print(f"📦 묶음 감지: {stats['bundle_detected']:,}개 ({stats['bundle_detected']/stats['total']*100:.1f}%)")
    print(f"✅ ISBN 발견: {stats['isbn_found']:,}개 ({stats['isbn_found']/stats['bundle_detected']*100:.1f}% of bundles)")
    print(f"❌ ISBN 없음: {stats['isbn_not_found']:,}개")
    print(f"⚠️  단일 상품: {stats['not_bundle']:,}개 (묶음 아님)")
    print()

    # 샘플 출력 (처음 10개)
    if updated_listings:
        print("📝 추출 샘플 (처음 10개):")
        print("-" * 80)
        for listing_id, isbn, product_name in updated_listings[:10]:
            isbn_count = len(isbn.split(','))
            print(f"ID {listing_id:5d} | ISBN ({isbn_count}개): {isbn[:40]:40s} | {product_name[:35]}")
        print()

    if not dry_run:
        # 실제 업데이트 수행
        print("💾 데이터베이스 업데이트 중...")

        update_count = 0
        for listing_id, isbn_str, _ in updated_listings:
            try:
                cursor.execute("UPDATE listings SET isbn = ? WHERE id = ?", (isbn_str, listing_id))
                update_count += 1

                # 50개마다 커밋 (체크포인트)
                if update_count % 50 == 0:
                    conn.commit()
                    print(f"   체크포인트: {update_count:,}개 커밋됨")
            except Exception as e:
                print(f"⚠️  ID {listing_id} 업데이트 실패: {e}")
                conn.rollback()
                continue

        # 최종 커밋
        conn.commit()
        print(f"✅ 업데이트 완료: {update_count:,}개")
    else:
        print("⚠️  DRY RUN 모드 - 변경사항이 저장되지 않았습니다")

    conn.close()

    print()
    print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='묶음 상품 분리 처리')
    parser.add_argument('--dry-run', action='store_true', help='변경사항을 저장하지 않고 미리보기만')
    parser.add_argument('--limit', type=int, help='처리할 최대 레코드 수 (테스트용)')
    parser.add_argument('--db', type=str, help='사용할 DB 파일 경로 (기본값: coupang_auto_backup.db)')
    parser.add_argument('--verbose', '-v', action='store_true', help='상세 로그 출력')

    args = parser.parse_args()

    # 기본값으로 backup DB 사용
    db_path = args.db or 'coupang_auto.db'

    try:
        stats = detect_and_split_bundles(
            dry_run=args.dry_run,
            limit=args.limit,
            db_path=db_path,
            verbose=args.verbose
        )

        print()
        print("📊 최종 통계:")
        print(f"   묶음 감지율: {stats['bundle_detected']/stats['total']*100:.1f}%")
        print(f"   ISBN 발견율: {stats['isbn_found']/stats['bundle_detected']*100:.1f}% (묶음 중)")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
