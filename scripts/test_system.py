"""시스템 테스트 (목 데이터 사용)"""
import sys
from pathlib import Path

# 프로젝트 루트를 파이썬 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal, init_db
from app.models.kyobo_product import KyoboProduct
from app.models.account import Account
from uploaders.csv_uploader import CSVUploader
from datetime import datetime


def create_mock_products():
    """테스트용 목 데이터 생성"""
    print("\n" + "="*60)
    print("Test Data Creation")
    print("="*60)

    mock_data = [
        {
            "isbn": "9788956746425",
            "title": "초등 수학 문제집 3학년 1학기",
            "author": "교육연구소",
            "publisher": "천재교육",
            "original_price": 15000,
            "category": "초등교재",
            "image_url": "https://contents.kyobobook.co.kr/sih/fit-in/458x0/pdt/123456789.jpg"
        },
        {
            "isbn": "9788956746426",
            "title": "초등 국어 독해력 향상 4학년",
            "author": "언어교육팀",
            "publisher": "비상교육",
            "original_price": 13500,
            "category": "초등교재",
            "image_url": "https://contents.kyobobook.co.kr/sih/fit-in/458x0/pdt/123456790.jpg"
        },
        {
            "isbn": "9788956746427",
            "title": "중등 영어 문법 총정리",
            "author": "영어교육연구소",
            "publisher": "능률교육",
            "original_price": 18000,
            "category": "중등교재",
            "image_url": "https://contents.kyobobook.co.kr/sih/fit-in/458x0/pdt/123456791.jpg"
        },
        {
            "isbn": "9788956746428",
            "title": "초등 과학 실험 교과서",
            "author": "과학교육팀",
            "publisher": "동아출판",
            "original_price": 16500,
            "category": "초등교재",
            "image_url": "https://contents.kyobobook.co.kr/sih/fit-in/458x0/pdt/123456792.jpg"
        },
        {
            "isbn": "9788956746429",
            "title": "수능 국어 독해 기본서",
            "author": "입시전문가팀",
            "publisher": "메가스터디",
            "original_price": 22000,
            "category": "수능교재",
            "image_url": "https://contents.kyobobook.co.kr/sih/fit-in/458x0/pdt/123456793.jpg"
        }
    ]

    db = SessionLocal()
    saved_products = []

    try:
        for data in mock_data:
            # 중복 체크
            existing = db.query(KyoboProduct).filter(
                KyoboProduct.isbn == data["isbn"]
            ).first()

            if existing:
                print(f"[Skip] Already exists: {data['title'][:30]}")
                saved_products.append(existing)
                continue

            # 새로 저장
            product = KyoboProduct(
                isbn=data["isbn"],
                title=data["title"],
                author=data["author"],
                publisher=data["publisher"],
                original_price=data["original_price"],
                category=data["category"],
                image_url=data["image_url"],
                crawled_at=datetime.utcnow(),
                is_processed=False
            )

            db.add(product)
            saved_products.append(product)
            print(f"[OK] Created: {data['title'][:40]}")

        db.commit()
        print(f"\nSuccess: {len(saved_products)} products in database")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

    return saved_products


def generate_csv_files():
    """CSV 파일 생성"""
    print("\n" + "="*60)
    print("CSV Generation Test")
    print("="*60)

    db = SessionLocal()

    try:
        # DB에서 상품 가져오기
        products = db.query(KyoboProduct).limit(10).all()

        if not products:
            print("No products in database")
            return

        # 쿠팡용 데이터 변환
        coupang_products = []
        for p in products:
            sale_price = int(p.original_price * 0.9)  # 10% 할인
            coupang_products.append({
                "product_name": f"{p.title} [10% Discount]",
                "original_price": p.original_price,
                "sale_price": sale_price,
                "isbn": p.isbn,
                "publisher": p.publisher,
                "author": p.author,
                "category": "Books/Textbooks",
                "main_image_url": p.image_url,
                "description": f"Title: {p.title}\nPublisher: {p.publisher}\nPrice: {p.original_price:,} won\nSale: {sale_price:,} won (10% off)"
            })

        # 계정 정보 가져오기
        accounts = db.query(Account).filter(Account.is_active == True).all()

        if not accounts:
            print("No accounts registered. Creating CSV with default account names...")
            account_names = ["account_1", "account_2", "account_3", "account_4", "account_5"]
        else:
            account_names = [acc.account_name for acc in accounts]

        # CSV 생성
        uploader = CSVUploader()
        result = uploader.generate_batch_csvs(coupang_products, account_names)

        print(f"\nCSV files created:")
        for account, filepath in result.items():
            print(f"  {account}: {filepath}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()


def check_accounts():
    """계정 등록 확인"""
    print("\n" + "="*60)
    print("Account Registration Check")
    print("="*60)

    db = SessionLocal()

    try:
        accounts = db.query(Account).all()

        if not accounts:
            print("No accounts registered yet.")
            print("\nRun this command to register accounts:")
            print("  python scripts/register_accounts.py")
            return False
        else:
            print(f"Registered accounts: {len(accounts)}\n")
            for acc in accounts:
                status = "Active" if acc.is_active else "Inactive"
                print(f"  [{status}] {acc.account_name}: {acc.email}")
            return True

    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        db.close()


def main():
    """전체 테스트 실행"""
    print("\n" + "="*60)
    print("Coupang Book Sales Automation System - System Test")
    print("="*60)

    # DB 초기화
    print("\nInitializing database...")
    init_db()
    print("OK: Database initialized")

    # 계정 확인
    has_accounts = check_accounts()

    # 목 데이터 생성
    products = create_mock_products()

    # CSV 생성
    if products:
        generate_csv_files()

        print("\n" + "="*60)
        print("Test Completed!")
        print("="*60)
        print("\nNext steps:")
        print("1. Check CSV files: data/uploads/")
        print("2. Upload CSV to Coupang Seller Center")
        if not has_accounts:
            print("3. Register accounts: python scripts/register_accounts.py")
        print()


if __name__ == "__main__":
    main()
