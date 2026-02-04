"""5개 계정 자동 업로드 스크립트"""
import sys
from pathlib import Path
import asyncio

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal
from app.models.account import Account
from app.models.kyobo_product import KyoboProduct
from uploaders.coupang_auto_uploader import CoupangAutoUploader
import logging

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


async def upload_to_all_accounts():
    """5개 계정에 모두 업로드"""

    print("\n" + "="*60)
    print("Coupang Auto Upload - All Accounts")
    print("="*60)

    db = SessionLocal()

    try:
        # 계정 조회
        accounts = db.query(Account).filter(Account.is_active == True).all()

        if not accounts:
            print("\n✗ No active accounts found.")
            print("  Run: python scripts/register_accounts.py")
            return

        print(f"\nFound {len(accounts)} active accounts:")
        for acc in accounts:
            print(f"  - {acc.account_name}: {acc.email}")

        # 상품 조회
        products = db.query(KyoboProduct).limit(5).all()

        if not products:
            print("\n✗ No products in database.")
            print("  Run: python scripts/test_system.py")
            return

        print(f"\nFound {len(products)} products to upload:")
        for p in products:
            print(f"  - {p.title[:50]}")

        # 상품 데이터 변환
        product_data_list = []
        for p in products:
            sale_price = int(p.original_price * 0.9)
            product_data_list.append({
                "product_name": f"{p.title} [10% Discount]",
                "original_price": p.original_price,
                "sale_price": sale_price,
                "isbn": p.isbn,
                "publisher": p.publisher,
                "author": p.author,
                "category": "Books/Textbooks"
            })

        print(f"\n{'='*60}")
        print("Starting upload process...")
        print("="*60)

        uploader = CoupangAutoUploader(headless=False)

        # 각 계정별로 업로드
        for i, account in enumerate(accounts, 1):
            print(f"\n{'='*60}")
            print(f"Account {i}/{len(accounts)}: {account.account_name}")
            print(f"{'='*60}")

            # 로그인
            logger.info(f"Logging in: {account.email}")
            login_success = await uploader.login(account)

            if not login_success:
                logger.error(f"Login failed for {account.account_name}")
                continue

            logger.info("Login successful!")

            # 상품 업로드
            logger.info(f"Uploading {len(product_data_list)} products...")

            results = await uploader.upload_batch(
                account,
                product_data_list,
                max_per_day=5  # 테스트용 5개만
            )

            # 결과 요약
            success_count = sum(1 for r in results if r["success"])
            logger.info(f"Upload complete: {success_count}/{len(results)} successful")

            # 다음 계정 전에 대기 (30초)
            if i < len(accounts):
                logger.info("Waiting 30 seconds before next account...")
                await asyncio.sleep(30)

        print(f"\n{'='*60}")
        print("All uploads completed!")
        print("="*60)

    except Exception as e:
        logger.error(f"Error: {e}")

    finally:
        db.close()


if __name__ == "__main__":
    print("\n⚠️  IMPORTANT:")
    print("  - This script will open browsers and attempt automatic login")
    print("  - You may need to solve CAPTCHAs manually")
    print("  - The first upload might take longer")
    print("  - Sessions will be saved for faster subsequent uploads")
    print()

    response = input("Continue? (y/n): ")

    if response.lower() == 'y':
        asyncio.run(upload_to_all_accounts())
    else:
        print("Cancelled.")
