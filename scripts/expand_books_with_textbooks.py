"""
Books 테이블 확장 - 주요 교재 시리즈 크롤링

주요 교재 시리즈를 알라딘 API로 크롤링하여 Books 테이블에 추가합니다.
- 분석 결과 기반 주요 시리즈 20개
- 시리즈별 전체 상품 크롤링
- 중복 제거 후 Books 추가
"""
import sys
import io
import os
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict

# UTF-8 출력 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

import sqlite3
from crawlers.aladin_api_crawler import AladinAPICrawler


# 주요 교재 시리즈 (분석 결과 기반)
MAJOR_TEXTBOOK_SERIES = [
    # 고등 수학/과학
    ('개념원리', ['수학', '물리', '화학']),
    ('쎈', ['수학']),
    ('자이스토리', ['수학', '물리', '화학', '생명과학', '지구과학']),
    ('마더텅', ['수학', '영어', '국어', '과학']),
    ('완자', ['수학', '과학', '사회']),
    ('오투', ['과학']),
    ('풍산자', ['수학']),
    ('일품', ['수학', '과학']),

    # 중등
    ('한끝', ['수학', '과학', '사회', '역사']),
    ('내신콘서트', ['영어', '수학', '국어']),

    # 수능
    ('수능특강', ['국어', '영어', '수학', '사회', '과학']),
    ('수능완성', ['국어', '영어', '수학']),
    ('EBS', ['국어', '영어', '수학']),

    # 초등
    ('디딤돌', ['수학']),
    ('우등생', ['수학', '과학']),
    ('최상위', ['수학']),
]


def search_textbook_series(
    crawler: AladinAPICrawler,
    series_name: str,
    subjects: List[str],
    max_per_query: int = 50
) -> List[Dict]:
    """
    특정 시리즈의 교재를 알라딘에서 검색

    Args:
        crawler: 알라딘 크롤러
        series_name: 시리즈명 (예: "오투")
        subjects: 과목 리스트 (예: ["수학", "과학"])
        max_per_query: 쿼리당 최대 결과 수

    Returns:
        도서 정보 리스트
    """
    all_books = []

    # 시리즈명만으로 검색
    try:
        print(f"  검색: {series_name}")
        results = crawler.search_by_keyword(
            keyword=series_name,
            max_results=max_per_query,
            sort='PublishTime'  # 최신순
        )

        if results:
            print(f"    → {len(results)}개 발견")
            all_books.extend(results)

        time.sleep(0.5)  # API 제한
    except Exception as e:
        print(f"    [에러] {str(e)[:50]}")

    # 시리즈명 + 과목으로 검색
    for subject in subjects:
        try:
            keyword = f"{series_name} {subject}"
            print(f"  검색: {keyword}")

            results = crawler.search_by_keyword(
                keyword=keyword,
                max_results=max_per_query,
                sort='PublishTime'
            )

            if results:
                print(f"    → {len(results)}개 발견")
                all_books.extend(results)

            time.sleep(0.5)  # API 제한
        except Exception as e:
            print(f"    [에러] {str(e)[:50]}")

    return all_books


def extract_book_info(aladin_item: Dict) -> Dict:
    """
    알라딘 API 결과에서 Book 정보 추출

    Returns:
        {
            'isbn': ISBN-13,
            'title': 제목,
            'author': 저자,
            'publisher_name': 출판사,
            'year': 출판연도,
            'list_price': 정가
        }
    """
    isbn = aladin_item.get('isbn13') or aladin_item.get('isbn')

    # pubDate에서 연도 추출
    pub_date = aladin_item.get('pubDate', '')
    year = None
    if pub_date:
        try:
            year = int(pub_date[:4])
        except:
            pass

    return {
        'isbn': isbn,
        'title': aladin_item.get('title', ''),
        'author': aladin_item.get('author', ''),
        'publisher_name': aladin_item.get('publisher', ''),
        'year': year,
        'list_price': aladin_item.get('priceStandard', 0)
    }


def insert_books_to_db(books: List[Dict], conn, dry_run: bool = False) -> tuple:
    """
    Books 테이블에 도서 추가 (중복 제거)

    Returns:
        (추가된 수, 중복 수)
    """
    cursor = conn.cursor()

    added = 0
    duplicates = 0

    for book in books:
        isbn = book['isbn']

        if not isbn:
            continue

        # 중복 체크
        cursor.execute("SELECT COUNT(*) FROM books WHERE isbn = ?", (isbn,))
        if cursor.fetchone()[0] > 0:
            duplicates += 1
            continue

        if not dry_run:
            try:
                cursor.execute("""
                    INSERT INTO books (isbn, title, author, publisher_name, year, list_price, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    book['isbn'],
                    book['title'],
                    book['author'],
                    book['publisher_name'],
                    book['year'],
                    book['list_price'],
                    datetime.utcnow()
                ))
                added += 1
            except Exception as e:
                print(f"      [삽입 에러] ISBN {isbn}: {str(e)[:50]}")

    if not dry_run:
        conn.commit()

    return added, duplicates


def expand_books_with_textbooks(
    dry_run: bool = False,
    db_path: str = 'coupang_auto_backup.db',
    series_limit: int = None
):
    """
    Books 테이블을 주요 교재로 확장

    Args:
        dry_run: 미리보기 모드
        db_path: DB 경로
        series_limit: 처리할 시리즈 수 제한 (테스트용)
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
    print("Books 테이블 확장 - 주요 교재 시리즈 크롤링")
    print("=" * 80)
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모드: {'DRY RUN (미리보기)' if dry_run else 'LIVE (실제 추가)'}")
    if series_limit:
        print(f"제한: 최대 {series_limit}개 시리즈")
    print()

    # 현재 Books 테이블 상태
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM books")
    initial_count = cursor.fetchone()[0]
    print(f"📚 현재 Books 테이블: {initial_count:,}개")
    print()

    # 통계
    stats = {
        'series_processed': 0,
        'total_found': 0,
        'total_added': 0,
        'total_duplicates': 0,
        'by_series': {}
    }

    # 시리즈별 크롤링
    series_to_process = MAJOR_TEXTBOOK_SERIES[:series_limit] if series_limit else MAJOR_TEXTBOOK_SERIES

    for idx, (series_name, subjects) in enumerate(series_to_process, 1):
        print(f"[{idx}/{len(series_to_process)}] 시리즈: {series_name}")

        # 검색
        aladin_results = search_textbook_series(crawler, series_name, subjects)

        # 중복 제거 (ISBN 기준)
        unique_books = {}
        for item in aladin_results:
            book_info = extract_book_info(item)
            isbn = book_info['isbn']
            if isbn and isbn not in unique_books:
                unique_books[isbn] = book_info

        books = list(unique_books.values())

        print(f"  중복 제거 후: {len(books)}개")

        # DB 삽입
        added, duplicates = insert_books_to_db(books, conn, dry_run)

        print(f"  결과: 추가 {added}개, 중복 {duplicates}개")
        print()

        stats['series_processed'] += 1
        stats['total_found'] += len(aladin_results)
        stats['total_added'] += added
        stats['total_duplicates'] += duplicates
        stats['by_series'][series_name] = {
            'found': len(aladin_results),
            'unique': len(books),
            'added': added,
            'duplicates': duplicates
        }

        # API 제한 준수
        time.sleep(1.0)

    # 최종 상태
    cursor.execute("SELECT COUNT(*) FROM books")
    final_count = cursor.fetchone()[0]

    print("=" * 80)
    print("크롤링 결과")
    print("=" * 80)
    print(f"처리한 시리즈: {stats['series_processed']}개")
    print(f"발견한 도서: {stats['total_found']:,}개")
    print(f"중복 제거 후: {stats['total_found'] - stats['total_duplicates']:,}개")
    print(f"추가된 도서: {stats['total_added']:,}개")
    print(f"중복 스킵: {stats['total_duplicates']:,}개")
    print()

    print("📚 Books 테이블:")
    print(f"  이전: {initial_count:,}개")
    print(f"  현재: {final_count:,}개")
    print(f"  증가: +{final_count - initial_count:,}개")
    print()

    # 시리즈별 상세
    print("📊 시리즈별 상세:")
    print("-" * 80)
    for series, data in sorted(stats['by_series'].items(), key=lambda x: -x[1]['added'])[:10]:
        print(f"{series:15s}: 발견 {data['found']:3d}개 → 추가 {data['added']:3d}개 (중복 {data['duplicates']:3d})")

    print()
    print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    conn.close()

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Books 테이블 확장')
    parser.add_argument('--dry-run', action='store_true', help='미리보기 모드')
    parser.add_argument('--db', type=str, default='coupang_auto_backup.db', help='DB 경로')
    parser.add_argument('--limit', type=int, help='시리즈 수 제한 (테스트용)')

    args = parser.parse_args()

    try:
        stats = expand_books_with_textbooks(
            dry_run=args.dry_run,
            db_path=args.db,
            series_limit=args.limit
        )

        print()
        print("✅ 크롤링 완료!")
        if not args.dry_run:
            print("💡 다음 단계: python scripts/fill_isbn_smart_matching.py")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
