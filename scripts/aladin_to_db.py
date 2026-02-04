"""알라딘 API → DB 저장 → CSV 생성"""
import sys
from pathlib import Path
import os

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from crawlers.aladin_api_crawler import AladinAPICrawler
from app.database import SessionLocal
from app.models.kyobo_product import KyoboProduct
from app.models.account import Account
from uploaders.coupang_csv_generator import CoupangCSVGenerator
from datetime import datetime


def main():
    """알라딘 API로 도서 검색 → DB 저장 → CSV 생성"""

    print("\n" + "🚀 "*30)
    print("알라딘 API → 쿠팡 CSV 자동 생성")
    print("🚀 "*30)

    # TTBKey 확인
    ttb_key = os.getenv("ALADIN_TTB_KEY")

    if not ttb_key:
        print("\n⚠️  알라딘 TTBKey가 필요합니다.")
        print("\n발급 방법:")
        print("1. https://www.aladin.co.kr/ttb/wblog_manage.aspx 접속")
        print("2. 알라딘 로그인")
        print("3. TTB 키 발급")
        print("4. .env 파일에 추가: ALADIN_TTB_KEY=your_key")
        print()

        ttb_key = input("TTBKey를 입력하세요 (또는 Enter=종료): ").strip()

        if not ttb_key:
            print("종료합니다.")
            return

    # 크롤러 초기화
    crawler = AladinAPICrawler(ttb_key=ttb_key)

    # 검색 키워드 입력
    print("\n" + "="*60)
    print("검색 설정")
    print("="*60)

    keyword = input("\n검색 키워드 (예: 초등수학): ").strip() or "초등교재"

    max_results_input = input("최대 검색 개수 (기본 20): ").strip()
    try:
        max_results = int(max_results_input) if max_results_input else 20
    except:
        max_results = 20

    # 검색
    print("\n" + "="*60)
    print(f"알라딘 API 검색: '{keyword}'")
    print("="*60)

    products = crawler.search_by_keyword(keyword, max_results=max_results)

    if not products:
        print("\n검색 결과가 없습니다.")
        return

    print(f"\n✅ 검색 완료: {len(products)}개")

    # 결과 미리보기
    print("\n" + "="*60)
    print("검색 결과 미리보기")
    print("="*60)

    for i, p in enumerate(products[:5], 1):
        print(f"\n{i}. {p['title'][:50]}")
        print(f"   저자: {p['author']}")
        print(f"   출판사: {p['publisher']}")
        print(f"   가격: {p['original_price']:,}원")

    if len(products) > 5:
        print(f"\n... 외 {len(products) - 5}개")

    # 확인
    proceed = input("\n\nDB에 저장하시겠습니까? (y/n): ").strip().lower()

    if proceed != 'y':
        print("취소되었습니다.")
        return

    # DB 저장
    save_to_db(products)

    # CSV 생성
    generate_csvs(products)


def save_to_db(products):
    """DB에 저장"""
    print("\n" + "="*60)
    print("데이터베이스 저장")
    print("="*60)

    db = SessionLocal()
    saved = 0
    skipped = 0

    try:
        for product in products:
            # ISBN이 없으면 건너뛰기
            if not product.get("isbn"):
                skipped += 1
                continue

            # 중복 체크
            existing = db.query(KyoboProduct).filter(
                KyoboProduct.isbn == product["isbn"]
            ).first()

            if existing:
                print(f"⏭️  이미 존재: {product['title'][:40]}")
                skipped += 1
                continue

            # 저장
            kyobo_product = KyoboProduct(
                isbn=product["isbn"],
                title=product["title"],
                author=product["author"],
                publisher=product["publisher"],
                original_price=product["original_price"],
                category=product["category"],
                subcategory=product["subcategory"],
                image_url=product["image_url"],
                description=product["description"],
                kyobo_url=product["kyobo_url"],
                publish_date=product["publish_date"],
                crawled_at=datetime.utcnow(),
                is_processed=False
            )

            db.add(kyobo_product)
            saved += 1
            print(f"✓ 저장: {product['title'][:40]}")

        db.commit()

        print(f"\n✅ DB 저장 완료!")
        print(f"   저장: {saved}개")
        print(f"   건너뜀: {skipped}개")

    except Exception as e:
        print(f"\n❌ DB 저장 오류: {e}")
        db.rollback()

    finally:
        db.close()


def generate_csvs(products):
    """CSV 생성"""
    print("\n" + "="*60)
    print("쿠팡 CSV 생성")
    print("="*60)

    # 계정 조회
    db = SessionLocal()
    accounts = db.query(Account).filter(Account.is_active == True).all()

    if accounts:
        account_names = [acc.account_name for acc in accounts]
    else:
        account_names = ["account_1", "account_2", "account_3", "account_4", "account_5"]

    db.close()

    # 상품 데이터 변환
    product_data = []
    for p in products:
        if not p.get("isbn"):  # ISBN 없으면 건너뛰기
            continue

        sale_price = int(p["original_price"] * 0.9)
        product_data.append({
            "product_name": p["title"],
            "original_price": p["original_price"],
            "sale_price": sale_price,
            "isbn": p["isbn"],
            "publisher": p["publisher"],
            "author": p["author"],
            "main_image_url": p["image_url"],
            "description": p["description"] or "상세페이지 참조"
        })

    if not product_data:
        print("\n생성할 상품이 없습니다.")
        return

    # CSV 생성
    generator = CoupangCSVGenerator()
    result = generator.generate_batch_csvs(product_data, account_names)

    print(f"\n✅ CSV 생성 완료:")
    for account, filepath in result.items():
        print(f"   {account}: {filepath}")

    print("\n" + "="*60)
    print("완료!")
    print("="*60)
    print("\n다음 단계:")
    print("1. data/uploads/ 폴더 확인")
    print("2. 쿠팡 판매자센터 > 상품관리 > 일괄등록")
    print("3. CSV 파일 업로드")
    print()


if __name__ == "__main__":
    main()
