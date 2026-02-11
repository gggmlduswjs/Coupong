"""
Phase 3: 알라딘 API 검색 강화 스크립트

기존 fill_isbn_from_aladin.py의 개선 버전:
- 연도 보존 (제거하지 않고 검색에 활용)
- 퍼블리셔 활용 (결과 필터링)
- 키워드 확장 (5단어 → 10단어)
- 정렬 개선 (연도 있으면 PublishTime, 없으면 Accuracy)

예상 성과: +1,000~1,500 ISBN (30-40분, 병렬 처리 시)
"""
import re
import sys
import io
import os
import time
from pathlib import Path
from datetime import datetime
from typing import Tuple, List, Optional, Dict

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


def extract_year(product_name: str) -> Optional[int]:
    """
    상품명에서 연도 추출

    패턴:
    - 2024, 2025, 2026, 2027 (20XX)
    - 2024년, 2025년

    Returns:
        연도 (int) 또는 None
    """
    if not product_name:
        return None

    # "YYYY년" 패턴
    match = re.search(r'(20\d{2})년', product_name)
    if match:
        year = int(match.group(1))
        if 2020 <= year <= 2030:
            return year

    # "YYYY" 패턴 (20XX)
    match = re.search(r'\b(20\d{2})\b', product_name)
    if match:
        year = int(match.group(1))
        if 2020 <= year <= 2030:
            return year

    return None


def extract_publisher(product_name: str) -> Optional[str]:
    """
    상품명에서 퍼블리셔 추출

    패턴:
    - [퍼블리셔명]
    - (퍼블리셔명)

    Returns:
        퍼블리셔명 또는 None
    """
    if not product_name:
        return None

    # [대괄호] 패턴 우선
    match = re.search(r'\[([^\]]+)\]', product_name)
    if match:
        publisher = match.group(1).strip()
        # 너무 길지 않고 의미 있는 경우만
        if 2 <= len(publisher) <= 20:
            return publisher

    # (소괄호) 패턴
    match = re.search(r'\(([^)]+)\)', product_name)
    if match:
        publisher = match.group(1).strip()
        # 연도, 권수, 판 정보 제외
        if not re.search(r'^\d|권|판|세트', publisher):
            if 2 <= len(publisher) <= 20:
                return publisher

    return None


def clean_title_for_search_enhanced(product_name: str, preserve_year: bool = True) -> str:
    """
    상품명을 알라딘 검색용 키워드로 정리 (강화 버전)

    개선사항:
    - 연도 보존 옵션 (기본값: True)
    - 퍼블리셔 정보는 제거하되 별도로 추출 가능
    - + & 기호는 제거 (묶음 구분자)

    Args:
        product_name: 원본 상품명
        preserve_year: True이면 연도 유지, False이면 제거

    Returns:
        정리된 검색 키워드
    """
    if not product_name:
        return ""

    title = product_name

    # 괄호 제거 (퍼블리셔 정보)
    title = re.sub(r'\[[^\]]*\]', '', title)
    title = re.sub(r'\([^)]*\)', '', title)

    # 연도 처리
    if not preserve_year:
        title = re.sub(r'\d{4}년?', '', title)
        title = re.sub(r'20\d{2}', '', title)

    # 세트, 권수 제거
    title = re.sub(r'세트\d*', '', title)
    title = re.sub(r'전\s*\d+권', '', title)
    title = re.sub(r'\d+권', '', title)

    # +, & 기호 제거 (묶음 구분자)
    title = re.sub(r'\s*[+&]\s*', ' ', title)

    # 불필요한 키워드 제거
    remove_words = ['선물', '사은품', '증정', '포함', '무료배송', '쁘띠', '선택']
    for word in remove_words:
        title = title.replace(word, '')

    # 공백 정리
    title = ' '.join(title.split())

    return title.strip()


def build_smart_aladin_query(product_name: str) -> Dict[str, any]:
    """
    스마트 알라딘 검색 쿼리 생성

    전략:
    1. 연도가 있으면 보존하고 PublishTime 정렬
    2. 연도가 없으면 Accuracy 정렬
    3. 퍼블리셔 추출하여 결과 필터링용으로 활용
    4. 키워드는 10단어까지 확장

    Returns:
        {
            'keyword': 검색 키워드,
            'year': 연도 (or None),
            'publisher': 퍼블리셔 (or None),
            'sort': 정렬 방식
        }
    """
    year = extract_year(product_name)
    publisher = extract_publisher(product_name)

    # 연도 보존 여부 결정
    preserve_year = (year is not None)

    title = clean_title_for_search_enhanced(product_name, preserve_year=preserve_year)

    # 키워드 확장: 5단어 → 10단어
    keywords = ' '.join(title.split()[:10])

    # 정렬 방식 결정
    sort = 'PublishTime' if year else 'Accuracy'

    return {
        'keyword': keywords,
        'year': year,
        'publisher': publisher,
        'sort': sort
    }


def search_isbn_from_aladin_enhanced(
    product_name: str,
    crawler: AladinAPICrawler,
    max_results: int = 5
) -> Optional[str]:
    """
    알라딘 API로 ISBN 검색 (강화 버전)

    개선사항:
    - 스마트 쿼리 생성
    - 퍼블리셔 필터링
    - 연도 기반 정렬

    Returns:
        ISBN 또는 None
    """
    query = build_smart_aladin_query(product_name)

    keyword = query['keyword']
    year = query['year']
    publisher = query['publisher']
    sort = query['sort']

    if not keyword or len(keyword) < 3:
        return None

    try:
        # 알라딘 API 검색
        results = crawler.search_by_keyword(
            keyword=keyword,
            max_results=max_results,
            sort=sort
        )

        if not results:
            return None

        # 퍼블리셔 필터링 (있으면)
        if publisher:
            for item in results:
                item_pub = item.get('publisher', '')

                # 퍼블리셔 매칭
                if publisher.lower() in item_pub.lower():
                    # 연도 검증 (있으면)
                    if year:
                        pub_date = item.get('pubDate', '')
                        if str(year) in pub_date:
                            isbn = item.get('isbn13') or item.get('isbn')
                            if isbn:
                                return isbn
                    else:
                        isbn = item.get('isbn13') or item.get('isbn')
                        if isbn:
                            return isbn

        # 연도 필터링 (퍼블리셔 매칭 실패 시)
        if year:
            for item in results:
                pub_date = item.get('pubDate', '')
                if str(year) in pub_date:
                    isbn = item.get('isbn13') or item.get('isbn')
                    if isbn:
                        return isbn

        # 모든 필터링 실패 시 첫 번째 결과 사용
        isbn = results[0].get('isbn13') or results[0].get('isbn')
        return isbn

    except Exception as e:
        # print(f"      [알라딘 API 에러] {str(e)[:50]}")
        return None


def fill_isbn_from_aladin_enhanced(
    dry_run: bool = False,
    limit: int = None,
    db_path: str = None,
    account_id: int = None,
    api_delay: float = 1.0
):
    """
    알라딘 API로 ISBN 채우기 (강화 버전)

    Args:
        dry_run: True일 경우 변경사항을 커밋하지 않고 미리보기만
        limit: 처리할 최대 레코드 수 (테스트용)
        db_path: 사용할 DB 파일 경로
        account_id: 특정 계정만 처리 (None이면 전체)
        api_delay: API 호출 간 대기 시간 (초)
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
    print("Phase 3: 알라딘 API 검색 강화")
    print("=" * 80)
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모드: {'DRY RUN (미리보기)' if dry_run else 'LIVE (실제 업데이트)'}")
    if limit:
        print(f"제한: 최대 {limit}개 레코드")
    if account_id:
        print(f"계정 필터: account_id = {account_id}")
    print(f"API 호출 간격: {api_delay}초")
    print()

    # ISBN이 없고 상품명이 있는 listings 조회
    query = """
        SELECT id, account_id, product_name
        FROM listings
        WHERE isbn IS NULL
          AND product_name IS NOT NULL
          AND product_name != ''
    """

    params = []
    if account_id:
        query += " AND account_id = ?"
        params.append(account_id)

    query += " ORDER BY id"

    if limit:
        query += f" LIMIT {limit}"

    cursor = conn.cursor()
    cursor.execute(query, params)
    candidates = cursor.fetchall()

    print(f"🔍 대상 레코드: {len(candidates):,}개")
    print()

    # 통계
    stats = {
        'total': len(candidates),
        'success': 0,
        'failed': 0,
        'skipped': 0,
        'with_year': 0,
        'with_publisher': 0
    }

    updated_listings = []

    start_time = time.time()

    for idx, row in enumerate(candidates, 1):
        listing_id = row[0]
        acc_id = row[1]
        product_name = row[2]

        # 쿼리 분석
        query_info = build_smart_aladin_query(product_name)

        if query_info['year']:
            stats['with_year'] += 1
        if query_info['publisher']:
            stats['with_publisher'] += 1

        # ISBN 검색
        isbn = search_isbn_from_aladin_enhanced(product_name, crawler)

        if isbn:
            stats['success'] += 1
            updated_listings.append((listing_id, isbn, product_name))

            # 처음 5개만 출력
            if stats['success'] <= 5:
                print(f"✓ [성공] {product_name[:50]}...")
                print(f"   → ISBN: {isbn}")
                print(f"   → 쿼리: {query_info['keyword'][:60]}")
                if query_info['year']:
                    print(f"   → 연도: {query_info['year']}, 정렬: {query_info['sort']}")
                if query_info['publisher']:
                    print(f"   → 퍼블리셔: {query_info['publisher']}")
                print()
        else:
            stats['failed'] += 1

        # 진행 상황 출력 (50개마다)
        if idx % 50 == 0:
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            remaining = (len(candidates) - idx) / rate if rate > 0 else 0

            print(f"진행: {idx:,}/{len(candidates):,} ({idx/len(candidates)*100:.1f}%) - "
                  f"성공: {stats['success']:,}, 실패: {stats['failed']:,} - "
                  f"속도: {rate:.1f}개/초, 남은 시간: {remaining/60:.1f}분")

        # API 호출 간 대기
        time.sleep(api_delay)

    elapsed_total = time.time() - start_time

    print()
    print("=" * 80)
    print("처리 결과")
    print("=" * 80)
    print(f"총 처리: {stats['total']:,}개")
    print(f"✅ 성공: {stats['success']:,}개 ({stats['success']/stats['total']*100:.1f}%)")
    print(f"❌ 실패: {stats['failed']:,}개 ({stats['failed']/stats['total']*100:.1f}%)")
    print()
    print(f"📊 쿼리 분석:")
    print(f"   연도 포함: {stats['with_year']:,}개 ({stats['with_year']/stats['total']*100:.1f}%)")
    print(f"   퍼블리셔 포함: {stats['with_publisher']:,}개 ({stats['with_publisher']/stats['total']*100:.1f}%)")
    print()
    print(f"⏱️  처리 시간: {elapsed_total/60:.1f}분 ({stats['total']/elapsed_total*60:.1f}개/분)")
    print()

    # 샘플 출력 (처음 10개)
    if updated_listings:
        print("📝 추출 샘플 (처음 10개):")
        print("-" * 80)
        for listing_id, isbn, product_name in updated_listings[:10]:
            print(f"ID {listing_id:5d} | ISBN: {isbn} | {product_name[:50]}")
        print()

    if not dry_run:
        # 실제 업데이트 수행
        print("💾 데이터베이스 업데이트 중...")

        update_count = 0
        for listing_id, isbn, _ in updated_listings:
            try:
                cursor.execute("UPDATE listings SET isbn = ? WHERE id = ?", (isbn, listing_id))
                update_count += 1

                # 100개마다 커밋 (체크포인트)
                if update_count % 100 == 0:
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

    parser = argparse.ArgumentParser(description='알라딘 API 검색 강화')
    parser.add_argument('--dry-run', action='store_true', help='변경사항을 저장하지 않고 미리보기만')
    parser.add_argument('--limit', type=int, help='처리할 최대 레코드 수 (테스트용)')
    parser.add_argument('--db', type=str, help='사용할 DB 파일 경로 (기본값: coupang_auto_backup.db)')
    parser.add_argument('--account', type=int, help='특정 계정만 처리 (account_id)')
    parser.add_argument('--delay', type=float, default=1.0, help='API 호출 간 대기 시간 (초, 기본값: 1.0)')

    args = parser.parse_args()

    # 기본값으로 backup DB 사용
    db_path = args.db or 'coupang_auto_backup.db'

    try:
        stats = fill_isbn_from_aladin_enhanced(
            dry_run=args.dry_run,
            limit=args.limit,
            db_path=db_path,
            account_id=args.account,
            api_delay=args.delay
        )

        print()
        print("📊 최종 통계:")
        print(f"   성공률: {stats['success']/stats['total']*100:.1f}%")
        print(f"   연도 활용: {stats['with_year']:,}개")
        print(f"   퍼블리셔 활용: {stats['with_publisher']:,}개")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
