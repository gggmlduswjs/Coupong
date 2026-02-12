"""연도 추출 테스트 스크립트"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.models.book import Book


def test_year_extraction():
    """연도 추출 기능 테스트"""
    print("\n" + "="*60)
    print("연도 추출 테스트")
    print("="*60)

    # 테스트 케이스
    test_cases = [
        "2025 수능완성 국어영역",
        "개념원리 수학(상) 2024",
        "EBS 고등 예비과정 24년도",
        "2026 마더텅 수능기출문제집",
        "좋은책신사고 우공비 중등수학 1-1 (2025)",
        "디딤돌 초등수학 기본+응용 5-2",
        "천재교육 고등 국어 문법",
        "비상교육 오투 과학 중1 2024년",
    ]

    print("\n테스트 결과:")
    print("-" * 60)

    for i, title in enumerate(test_cases, 1):
        year = Book.extract_year(title)
        normalized_title = Book.normalize_title(title, year)
        series = Book.extract_series(normalized_title)

        print(f"\n{i}. 원본: {title}")
        print(f"   연도: {year if year else '(추출 실패)'}")
        print(f"   정규화: {normalized_title}")
        print(f"   시리즈: {series}")

    print("\n" + "="*60)
    print("테스트 완료")
    print("="*60)


def test_with_aladin_api():
    """알라딘 API로 실제 데이터 테스트"""
    import os
    from crawlers.aladin_api_crawler import AladinAPICrawler

    print("\n" + "="*60)
    print("알라딘 API 연도 추출 테스트")
    print("="*60)

    ttb_key = os.getenv("ALADIN_TTB_KEY")

    if not ttb_key:
        print("\n[WARNING] ALADIN_TTB_KEY가 설정되지 않았습니다.")
        print("ALADIN_API_GUIDE.md를 참고하여 TTBKey를 발급받으세요.")
        return

    crawler = AladinAPICrawler(ttb_key=ttb_key)

    # 2025년 교재 검색
    print("\n검색: '2025 수능'")
    print("-" * 60)

    products = crawler.search_by_keyword("2025 수능", max_results=5)

    if products:
        for i, p in enumerate(products, 1):
            print(f"\n{i}. {p['title']}")
            print(f"   ISBN: {p['isbn']}")
            print(f"   출판사: {p['publisher']}")
            print(f"   정가: {p['original_price']:,}원")

            if p.get('year'):
                print(f"   [연도 추출 성공] {p['year']}년")
                print(f"   정규화 제목: {p['normalized_title']}")
                print(f"   시리즈명: {p['normalized_series']}")
            else:
                print(f"   [연도 추출 실패]")
    else:
        print("\n검색 결과가 없습니다.")

    print("\n" + "="*60)
    print("API 테스트 완료")
    print("="*60)


if __name__ == "__main__":
    # 1. 정규식 테스트
    test_year_extraction()

    # 2. 알라딘 API 테스트 (TTBKey 있을 때만)
    proceed = input("\n알라딘 API로 실제 데이터 테스트할까요? (y/n): ").strip().lower()
    if proceed == 'y':
        test_with_aladin_api()
