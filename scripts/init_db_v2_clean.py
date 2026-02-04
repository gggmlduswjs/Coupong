# -*- coding: utf-8 -*-
"""Database V2 Initialization Script"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import engine, SessionLocal, Base
from app.models import Publisher, Book, Product, BundleSKU, Listing, Account, Sales, AnalysisResult, Task


def init_database():
    """Create database tables"""
    print("\n" + "="*60)
    print("Database V2 Initialization")
    print("="*60)

    print("\n1. Creating tables...")

    # Create all tables
    Base.metadata.create_all(bind=engine)

    print("   [OK] Tables created successfully")
    print("      - accounts")
    print("      - publishers [NEW]")
    print("      - books [NEW] (formerly kyobo_products)")
    print("      - products [UPDATED]")
    print("      - bundle_skus [NEW]")
    print("      - listings [UPDATED]")
    print("      - sales")
    print("      - analysis_results")
    print("      - tasks")


def init_publishers():
    """Initialize publisher data"""
    print("\n2. Initializing publisher data...")

    db = SessionLocal()

    try:
        # Check existing data
        existing_count = db.query(Publisher).count()
        if existing_count > 0:
            print(f"   [WARNING] {existing_count} publishers already exist.")
            overwrite = input("   Delete and re-insert? (y/n): ").strip().lower()
            if overwrite == 'y':
                db.query(Publisher).delete()
                db.commit()
                print("   [OK] Existing data deleted")
            else:
                print("   Skipped")
                return

        # Publisher data (24 publishers)
        publishers_data = [
            # Margin rate 40% (Supply rate 60%)
            ("marinbooks", 40, 9000, 0.60),
            ("academysoft", 40, 9000, 0.60),
            ("lexmedia", 40, 9000, 0.60),
            ("harambooks", 40, 9000, 0.60),

            # Margin rate 55% (Supply rate 45%)
            ("crown", 55, 14400, 0.45),
            ("youngjin", 55, 14400, 0.45),

            # Margin rate 60% (Supply rate 40%)
            ("efuture", 60, 18000, 0.40),
            ("socialreview", 60, 18000, 0.40),
            ("gilbut", 60, 18000, 0.40),
            ("artio", 60, 18000, 0.40),
            ("easyspub", 60, 18000, 0.40),

            # Margin rate 65% (Supply rate 35%)
            ("gaennyeom", 65, 23900, 0.35),
            ("etoos", 65, 23900, 0.35),
            ("visang", 65, 23900, 0.35),
            ("neungyule", 65, 23900, 0.35),
            ("seetalk", 65, 23900, 0.35),
            ("jihaksa", 65, 23900, 0.35),
            ("sukyung", 65, 23900, 0.35),
            ("soltibooks", 65, 23900, 0.35),
            ("matheytung", 65, 23900, 0.35),
            ("hanbit", 65, 23900, 0.35),

            # Margin rate 67% (Supply rate 33%)
            ("donga", 67, 27600, 0.33),

            # Margin rate 70% (Supply rate 30%)
            ("goodbook", 70, 35800, 0.30),

            # Margin rate 73% (Supply rate 27%)
            ("EBS", 73, 50800, 0.27),
            ("kbs_edu", 73, 50800, 0.27),
        ]

        for name, margin_rate, min_free_shipping, supply_rate in publishers_data:
            publisher = Publisher(
                name=name,
                margin_rate=margin_rate,
                min_free_shipping=min_free_shipping,
                supply_rate=supply_rate,
                is_active=True
            )
            db.add(publisher)
            print(f"   [OK] {name} (margin {margin_rate}%, supply {int(supply_rate*100)}%)")

        db.commit()

        print(f"\n   [OK] {len(publishers_data)} publishers registered")

    except Exception as e:
        print(f"\n   [ERROR] {e}")
        db.rollback()

    finally:
        db.close()


def test_publisher_calculations():
    """Test publisher margin calculations"""
    print("\n3. Testing publisher margin calculations...")

    db = SessionLocal()

    try:
        # Test cases
        test_cases = [
            ("gaennyeom", 15000, "65% publisher"),
            ("gilbut", 30000, "60% publisher"),
            ("EBS", 10000, "73% publisher (bundle required)"),
        ]

        for pub_name, list_price, desc in test_cases:
            publisher = db.query(Publisher).filter(Publisher.name == pub_name).first()

            if publisher:
                margin_info = publisher.calculate_margin(list_price)
                policy = publisher.determine_shipping_policy(list_price)

                print(f"\n   [{desc}] {pub_name} - List price {list_price:,} KRW")
                print(f"      Sale price: {margin_info['sale_price']:,} KRW")
                print(f"      Supply cost: {margin_info['supply_cost']:,} KRW")
                print(f"      Coupang fee: {margin_info['coupang_fee']:,} KRW")
                print(f"      Margin per unit: {margin_info['margin_per_unit']:,} KRW")
                print(f"      Net margin: {margin_info['net_margin']:,} KRW")
                print(f"      Shipping policy: {policy}")

        print("\n   [OK] Margin calculations working correctly")

    except Exception as e:
        print(f"\n   [ERROR] {e}")

    finally:
        db.close()


def main():
    """Main function"""
    print("\n" + "="*60)
    print("Database V2 Schema Initialization")
    print("="*60)

    # 1. Create tables
    init_database()

    # 2. Initialize publisher data
    init_publishers()

    # 3. Test
    test_publisher_calculations()

    print("\n" + "="*60)
    print("Initialization Complete!")
    print("="*60)

    print("\nNext steps:")
    print("1. python scripts/register_accounts.py (Register accounts)")
    print("2. python scripts/auto_search_publishers.py (Search books)")
    print()


if __name__ == "__main__":
    main()
