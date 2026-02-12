"""알라딘 API 연도 추출 실전 테스트"""
import sys
from pathlib import Path
import os

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# .env 파일 로드
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from crawlers.aladin_api_crawler import AladinAPICrawler


def main():
    """알라딘 API로 2025년 교재 검색 및 연도 추출 테스트"""
    print("\n" + "="*60)
    print("알라딘 API 연도 추출 실전 테스트")
    print("="*60)

    ttb_key = os.getenv("ALADIN_TTB_KEY")

    if not ttb_key:
        print("\n[ERROR] ALADIN_TTB_KEY가 설정되지 않았습니다.")
        print("ALADIN_API_GUIDE.md를 참고하여 TTBKey를 발급받으세요.")
        return

    crawler = AladinAPICrawler(ttb_key=ttb_key)

    # 테스트 검색어
    test_queries = [
        ("2025 수능", "2025년 수능 교재"),
        ("2024 EBS", "2024년 EBS 교재"),
        ("개념원리 2025", "개념원리 2025년 교재"),
    ]

    for keyword, description in test_queries:
        print(f"\n{'='*60}")
        print(f"검색: '{keyword}' ({description})")
        print("="*60)

        products = crawler.search_by_keyword(keyword, max_results=5)

        if products:
            year_extracted_count = 0

            for i, p in enumerate(products, 1):
                print(f"\n{i}. {p['title'][:60]}")
                print(f"   ISBN: {p['isbn']}")
                print(f"   출판사: {p['publisher']}")
                print(f"   정가: {p['original_price']:,}원")

                if p.get('year'):
                    print(f"   [OK] 연도: {p['year']}년")
                    print(f"   정규화: {p['normalized_title'][:50]}")
                    print(f"   시리즈: {p['normalized_series'][:40]}")
                    year_extracted_count += 1
                else:
                    print(f"   [WARNING] 연도 추출 실패")

            print(f"\n연도 추출 성공률: {year_extracted_count}/{len(products)} ({year_extracted_count/len(products)*100:.0f}%)")

        else:
            print("\n[WARNING] 검색 결과가 없습니다.")

    print("\n" + "="*60)
    print("테스트 완료")
    print("="*60)


if __name__ == "__main__":
    main()
