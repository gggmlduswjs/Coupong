"""
ISBN 없는 상품 분석 스크립트

ISBN이 없는 상품들의 패턴을 분석하여 개선 방향을 제시합니다.
"""
import sys
import io
import sqlite3
from collections import Counter
import re

# UTF-8 출력 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def analyze_missing_isbn(db_path='coupang_auto_backup.db'):
    """ISBN 없는 상품 분석"""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("=" * 80)
    print("ISBN 없는 상품 분석")
    print("=" * 80)
    print()

    # ISBN 없는 상품 조회
    cursor.execute("""
        SELECT product_name
        FROM listings
        WHERE (isbn IS NULL OR isbn = '')
        AND product_name IS NOT NULL
        LIMIT 1000
    """)

    no_isbn_products = [row[0] for row in cursor.fetchall()]

    print(f"분석 대상: {len(no_isbn_products)}개 샘플")
    print()

    # 1. 시리즈/브랜드 패턴 추출
    print("📚 주요 시리즈/브랜드 (상위 20개)")
    print("-" * 80)

    series_patterns = [
        r'^\[?([가-힣a-zA-Z]+)\]',  # [비상] 등
        r'^([가-힣a-zA-Z]+)\s+(?:중학|고등|초등)',  # "오투 중학" 등
        r'(마더텅|자이스토리|수능특강|완자|한끝|오투|개념플러스|일품|쎈|개념)',  # 주요 브랜드
    ]

    series_counter = Counter()

    for product_name in no_isbn_products:
        for pattern in series_patterns:
            match = re.search(pattern, product_name)
            if match:
                series_counter[match.group(1)] += 1
                break

    for series, count in series_counter.most_common(20):
        print(f"{series:20s}: {count:4d}개")

    print()

    # 2. 키워드 빈도 분석
    print("🔍 주요 키워드 (상위 30개)")
    print("-" * 80)

    keyword_counter = Counter()

    for product_name in no_isbn_products:
        # 의미 있는 단어 추출 (2글자 이상)
        words = re.findall(r'[가-힣a-zA-Z]{2,}', product_name)
        keyword_counter.update(words)

    # 불용어 제거
    stopwords = {'선물', '사은품', '증정', '포함', '무료', '세트', '전', '권'}

    filtered_keywords = [(k, v) for k, v in keyword_counter.most_common(50) if k not in stopwords]

    for keyword, count in filtered_keywords[:30]:
        print(f"{keyword:15s}: {count:4d}회")

    print()

    # 3. 연도 분포
    print("📅 연도 분포")
    print("-" * 80)

    year_counter = Counter()

    for product_name in no_isbn_products:
        years = re.findall(r'20\d{2}', product_name)
        year_counter.update(years)

    for year, count in sorted(year_counter.items(), reverse=True):
        print(f"{year}: {count:4d}개")

    print()

    # 4. 상품명 길이 분포
    print("📏 상품명 길이 분포")
    print("-" * 80)

    lengths = [len(p) for p in no_isbn_products]

    print(f"평균: {sum(lengths)/len(lengths):.1f}자")
    print(f"최소: {min(lengths)}자")
    print(f"최대: {max(lengths)}자")
    print(f"중간값: {sorted(lengths)[len(lengths)//2]}자")

    print()

    # 5. 샘플 출력
    print("📝 샘플 상품 (무작위 20개)")
    print("-" * 80)

    import random
    samples = random.sample(no_isbn_products, min(20, len(no_isbn_products)))

    for i, product_name in enumerate(samples, 1):
        print(f"{i:2d}. {product_name[:75]}")

    print()
    print("=" * 80)

    conn.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='ISBN 없는 상품 분석')
    parser.add_argument('--db', type=str, default='coupang_auto_backup.db', help='DB 파일 경로')

    args = parser.parse_args()

    try:
        analyze_missing_isbn(db_path=args.db)
    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
