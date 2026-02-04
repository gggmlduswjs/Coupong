"""빠른 시작 스크립트 - MVP 테스트용"""
import sys
from pathlib import Path
import asyncio

# 프로젝트 루트를 파이썬 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from crawlers.kyobo_crawler import KyoboCrawler
from uploaders.csv_uploader import CSVUploader
from app.database import SessionLocal, init_db
from app.models.kyobo_product import KyoboProduct
from datetime import datetime


async def test_crawler():
    """크롤러 테스트"""
    print("\n" + "="*60)
    print("1️⃣  교보문고 크롤링 테스트")
    print("="*60)

    crawler = KyoboCrawler()
    products = await crawler.crawl(category="초등교재", limit=5)

    print(f"\n✅ 수집 완료: {len(products)}개")
    for i, p in enumerate(products, 1):
        print(f"\n{i}. {p['title'][:40]}")
        print(f"   가격: {p['original_price']:,}원")
        print(f"   ISBN: {p['isbn']}")
        print(f"   출판사: {p['publisher']}")

    return products


def save_to_db(products):
    """DB 저장 테스트"""
    print("\n" + "="*60)
    print("2️⃣  데이터베이스 저장 테스트")
    print("="*60)

    db = SessionLocal()
    saved_count = 0

    try:
        for p in products:
            # 중복 체크
            existing = db.query(KyoboProduct).filter(
                KyoboProduct.isbn == p['isbn']
            ).first()

            if existing:
                print(f"⏭️  이미 존재: {p['title'][:30]}")
                continue

            # 새로 저장
            kyobo_product = KyoboProduct(
                isbn=p['isbn'],
                title=p['title'],
                author=p['author'],
                publisher=p['publisher'],
                original_price=p['original_price'],
                category=p['category'],
                subcategory=p['subcategory'],
                image_url=p['image_url'],
                description=p['description'],
                kyobo_url=p['kyobo_url'],
                publish_date=p['publish_date'],
                crawled_at=datetime.utcnow(),
                is_processed=False
            )

            db.add(kyobo_product)
            saved_count += 1

        db.commit()
        print(f"\n✅ DB 저장 완료: {saved_count}개")

    except Exception as e:
        print(f"❌ DB 저장 실패: {e}")
        db.rollback()
    finally:
        db.close()


def test_csv_generation(products):
    """CSV 생성 테스트"""
    print("\n" + "="*60)
    print("3️⃣  CSV 생성 테스트")
    print("="*60)

    # 상품 데이터 변환 (쿠팡용)
    coupang_products = []
    for p in products:
        sale_price = int(p['original_price'] * 0.9)  # 10% 할인
        coupang_products.append({
            "product_name": f"{p['title']} [10% 할인]",
            "original_price": p['original_price'],
            "sale_price": sale_price,
            "isbn": p['isbn'],
            "publisher": p['publisher'],
            "author": p['author'],
            "category": "도서/교재",
            "main_image_url": p['image_url'],
            "description": f"📚 {p['title']}\n\n✅ 정가: {p['original_price']:,}원\n✅ 할인가: {sale_price:,}원"
        })

    # CSV 생성
    uploader = CSVUploader()

    # 계정별 CSV 생성
    accounts = ["account_1", "account_2", "account_3", "account_4", "account_5"]
    result = uploader.generate_batch_csvs(coupang_products, accounts)

    print(f"\n✅ CSV 생성 완료:")
    for account, filepath in result.items():
        print(f"   {account}: {filepath}")


async def main():
    """전체 테스트 실행"""
    print("\n" + "🚀 "*30)
    print("쿠팡 도서 판매 자동화 시스템 - MVP 테스트")
    print("🚀 "*30)

    # DB 초기화
    print("\n🔧 데이터베이스 초기화...")
    init_db()
    print("✅ DB 초기화 완료")

    # 1. 크롤링
    products = await test_crawler()

    if not products:
        print("❌ 크롤링 실패. 종료합니다.")
        return

    # 2. DB 저장
    save_to_db(products)

    # 3. CSV 생성
    test_csv_generation(products)

    print("\n" + "="*60)
    print("✅ 모든 테스트 완료!")
    print("="*60)
    print("\n다음 단계:")
    print("1. data/uploads/ 폴더에서 생성된 CSV 확인")
    print("2. 쿠팡 판매자센터 → 상품관리 → 대량등록 → CSV 업로드")
    print("3. 판매 데이터 수집 → 분석 시작")
    print()


if __name__ == "__main__":
    asyncio.run(main())
