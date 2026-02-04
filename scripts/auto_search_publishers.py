"""출판사별 최신 도서 자동 검색 & 등록"""
import sys
from pathlib import Path
import os
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from crawlers.aladin_api_crawler import AladinAPICrawler
from app.database import SessionLocal
from app.models.kyobo_product import KyoboProduct
from app.models.account import Account
from uploaders.coupang_csv_generator import CoupangCSVGenerator
from config.publishers import PUBLISHERS, get_publisher_info, meets_free_shipping


def main():
    """출판사별 최신 도서 자동 검색"""

    print("\n" + "🚀 "*30)
    print("출판사별 최신 도서 자동 검색 시스템")
    print("🚀 "*30)

    # TTBKey 확인
    ttb_key = os.getenv("ALADIN_TTB_KEY")

    if not ttb_key:
        print("\n⚠️  알라딘 TTBKey가 필요합니다.")
        print("ALADIN_API_GUIDE.md 참고하여 발급받으세요.")
        return

    # 크롤러 초기화
    crawler = AladinAPICrawler(ttb_key=ttb_key)

    # 검색 설정
    print("\n" + "="*60)
    print("검색 설정")
    print("="*60)

    print(f"\n취급 출판사: {len(PUBLISHERS)}개")
    print("\n주요 출판사:")
    for pub in PUBLISHERS[:10]:
        print(f"  - {pub['name']} (매입률 {pub['margin']}%)")
    if len(PUBLISHERS) > 10:
        print(f"  ... 외 {len(PUBLISHERS) - 10}개")

    # 검색 옵션
    print("\n검색 모드:")
    print("1. 전체 출판사 자동 검색 (권장)")
    print("2. 특정 출판사만 선택")

    mode = input("\n선택 (1 or 2): ").strip() or "1"

    if mode == "2":
        publishers_to_search = select_publishers()
    else:
        publishers_to_search = PUBLISHERS

    # 출판사당 검색 개수
    max_per_publisher = input("\n출판사당 최대 검색 개수 (기본 10): ").strip()
    try:
        max_per_publisher = int(max_per_publisher) if max_per_publisher else 10
    except:
        max_per_publisher = 10

    # 최신도서 필터 (출간일 기준)
    days_back = input("\n최근 며칠 이내 출간 도서? (기본 365일): ").strip()
    try:
        days_back = int(days_back) if days_back else 365
    except:
        days_back = 365

    cutoff_date = datetime.now() - timedelta(days=days_back)

    # 검색 시작
    print("\n" + "="*60)
    print("알라딘 API 검색 중...")
    print("="*60)

    all_products = []
    filtered_products = []

    for pub in publishers_to_search:
        pub_name = pub["name"]
        print(f"\n🔍 [{pub_name}] 검색 중...")

        # 출판사 이름으로 검색
        products = crawler.search_by_keyword(pub_name, max_results=max_per_publisher)

        for p in products:
            # 출판사 필터링 (정확히 일치하는 것만)
            if pub_name not in p.get("publisher", ""):
                continue

            # 최신도서 필터링
            pub_date = p.get("publish_date")
            if pub_date and pub_date < cutoff_date.date():
                continue

            # 무료배송 기준 체크
            sale_price = int(p["original_price"] * 0.9)
            if not meets_free_shipping(pub_name, sale_price):
                print(f"   ⏭️  무료배송 미충족: {p['title'][:30]} ({sale_price:,}원 < {pub['min_free_shipping']:,}원)")
                continue

            all_products.append(p)
            filtered_products.append(p)
            print(f"   ✓ {p['title'][:40]} ({p['original_price']:,}원)")

        print(f"   결과: {len([p for p in filtered_products if pub_name in p['publisher']])}개")

    # 결과 요약
    print("\n" + "="*60)
    print("검색 결과 요약")
    print("="*60)
    print(f"\n총 검색: {len(all_products)}개")
    print(f"필터링 후: {len(filtered_products)}개")

    if not filtered_products:
        print("\n조건에 맞는 도서가 없습니다.")
        return

    # 미리보기
    print("\n" + "="*60)
    print("검색 결과 미리보기 (상위 10개)")
    print("="*60)

    for i, p in enumerate(filtered_products[:10], 1):
        pub_info = get_publisher_info(p['publisher'])
        sale_price = int(p['original_price'] * 0.9)

        print(f"\n{i}. {p['title'][:50]}")
        print(f"   출판사: {p['publisher']} (매입률 {pub_info['margin']}%)")
        print(f"   정가: {p['original_price']:,}원 → 판매가: {sale_price:,}원")
        print(f"   무료배송: {'✓' if meets_free_shipping(p['publisher'], sale_price) else '✗'}")

    if len(filtered_products) > 10:
        print(f"\n... 외 {len(filtered_products) - 10}개")

    # 확인
    proceed = input("\n\nDB 저장 및 CSV 생성하시겠습니까? (y/n): ").strip().lower()

    if proceed != 'y':
        print("취소되었습니다.")
        return

    # DB 저장
    save_to_db(filtered_products)

    # CSV 생성
    generate_csvs(filtered_products)


def select_publishers():
    """출판사 선택 (대화형)"""
    print("\n" + "="*60)
    print("출판사 선택")
    print("="*60)

    for i, pub in enumerate(PUBLISHERS, 1):
        print(f"{i:2d}. {pub['name']:20s} (매입률 {pub['margin']}%)")

    print("\n선택 방법:")
    print("- 번호 입력 (예: 1,3,5)")
    print("- 'all' 입력하면 전체 선택")

    choice = input("\n선택: ").strip()

    if choice.lower() == 'all':
        return PUBLISHERS

    try:
        indices = [int(x.strip()) - 1 for x in choice.split(",")]
        selected = [PUBLISHERS[i] for i in indices if 0 <= i < len(PUBLISHERS)]
        print(f"\n선택됨: {', '.join([p['name'] for p in selected])}")
        return selected
    except:
        print("잘못된 입력. 전체 출판사로 진행합니다.")
        return PUBLISHERS


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
        if not p.get("isbn"):
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
