"""쿠팡 공식 템플릿 CSV 생성 스크립트"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal
from app.models.kyobo_product import KyoboProduct
from app.models.account import Account
from uploaders.coupang_csv_generator import CoupangCSVGenerator


def main():
    """DB 상품으로 공식 템플릿 CSV 생성"""

    print("\n" + "=" * 60)
    print("Coupang Official Template CSV Generator")
    print("=" * 60)

    db = SessionLocal()

    try:
        # 상품 조회
        products = db.query(KyoboProduct).all()

        if not products:
            print("\nNo products in database.")
            print("Run: python scripts/test_system.py")
            return

        print(f"\nFound {len(products)} products")

        # 계정 조회
        accounts = db.query(Account).filter(Account.is_active == True).all()

        if accounts:
            account_names = [acc.account_name for acc in accounts]
            print(f"Found {len(accounts)} active accounts")
        else:
            account_names = ["account_1", "account_2", "account_3", "account_4", "account_5"]
            print("No accounts found. Using default names")

        # 상품 데이터 변환
        product_data = []
        for p in products:
            sale_price = int(p.original_price * 0.9)
            product_data.append({
                "product_name": p.title,
                "original_price": p.original_price,
                "sale_price": sale_price,
                "isbn": p.isbn,
                "publisher": p.publisher,
                "author": p.author,
                "main_image_url": p.image_url,
                "description": p.description or "상세페이지 참조"
            })

        # CSV 생성
        generator = CoupangCSVGenerator()
        result = generator.generate_batch_csvs(product_data, account_names)

        print("\n" + "=" * 60)
        print("CSV Generation Complete!")
        print("=" * 60)
        print("\nGenerated files:")
        for account, filepath in result.items():
            print(f"  {account}: {filepath}")

        print("\n" + "=" * 60)
        print("Next Steps:")
        print("=" * 60)
        print("1. Check CSV files: data/uploads/")
        print("2. Go to: https://wing.coupang.com")
        print("3. Navigate: 상품관리 > 일괄등록")
        print("4. Download template (if needed)")
        print("5. Upload your CSV files")
        print()

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

    finally:
        db.close()


if __name__ == "__main__":
    main()
