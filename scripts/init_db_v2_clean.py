# -*- coding: utf-8 -*-
"""
Database V3 Clean Initialization Script
========================================
drop_all() → create_all() — 전체 테이블 재생성

주의: 기존 데이터가 모두 삭제됩니다!
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from app.database import engine, SessionLocal, Base

# 모든 모델 import (Base.metadata에 등록)
from app.models import (
    Account, Publisher, Book, Product, BundleSKU, BundleItem,
    Listing, AnalysisResult,
    RevenueHistory, SettlementHistory, AdSpend, AdPerformance,
    Order, ReturnRequest,
)


def init_database(drop_first: bool = False):
    """테이블 생성 (drop_first=True면 기존 테이블 삭제 후 재생성)"""
    from sqlalchemy import text

    print("\n" + "=" * 60)
    print("  Database V3 Clean Initialization")
    print("=" * 60)

    if drop_first:
        print("\n[1/2] 기존 테이블 삭제...")
        # PostgreSQL: CASCADE로 모든 의존성 포함 삭제
        with engine.connect() as conn:
            # 현재 존재하는 모든 테이블 조회
            rows = conn.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )).fetchall()
            table_names = [r[0] for r in rows]
            if table_names:
                tables_str = ", ".join(table_names)
                conn.execute(text(f"DROP TABLE IF EXISTS {tables_str} CASCADE"))
                conn.commit()
                print(f"   [OK] {len(table_names)}개 테이블 CASCADE 삭제 완료")
            else:
                print("   [OK] 삭제할 테이블 없음")

    print(f"\n[{'2/2' if drop_first else '1/1'}] 테이블 생성...")
    Base.metadata.create_all(bind=engine)
    print("   [OK] 테이블 생성 완료")

    tables = [
        "accounts", "publishers", "books", "products",
        "bundle_skus", "bundle_items", "listings",
        "analysis_results", "revenue_history", "settlement_history",
        "ad_spends", "ad_performances", "orders", "return_requests",
    ]
    for t in tables:
        print(f"      - {t}")


def init_publishers():
    """출판사 시딩"""
    from config.publishers import PUBLISHERS
    from app.models import Publisher

    print("\n[출판사 시딩]")

    db = SessionLocal()
    try:
        existing = db.query(Publisher).count()
        if existing > 0:
            print(f"   이미 {existing}개 출판사 존재 → 건너뜀")
            return

        for pub_data in PUBLISHERS:
            margin = pub_data.get("margin_rate") or pub_data.get("margin")
            supply_rate = pub_data.get("supply_rate") or round((100 - margin) / 100, 2)
            publisher = Publisher(
                name=pub_data["name"],
                margin_rate=margin,
                min_free_shipping=pub_data.get("min_free_shipping", 0),
                supply_rate=supply_rate,
                is_active=True,
            )
            db.add(publisher)
            print(f"   + {pub_data['name']} (매입률 {margin}%)")

        db.commit()
        print(f"   [OK] {len(PUBLISHERS)}개 출판사 등록")

    except Exception as e:
        print(f"   [ERROR] {e}")
        db.rollback()
    finally:
        db.close()


def verify_schema():
    """스키마 검증"""
    from sqlalchemy import inspect

    print("\n[스키마 검증]")
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"   테이블 수: {len(tables)}")

    # 핵심 테이블 확인
    required = [
        "accounts", "publishers", "books", "products",
        "bundle_skus", "bundle_items", "listings",
    ]
    for t in required:
        if t in tables:
            cols = [c["name"] for c in inspector.get_columns(t)]
            print(f"   [OK] {t} ({len(cols)} 컬럼)")
        else:
            print(f"   [FAIL] {t} — 테이블 없음!")

    # Listing 핵심 컬럼 확인
    listing_cols = {c["name"] for c in inspector.get_columns("listings")}
    must_have = {"coupang_product_id", "vendor_item_id", "product_id", "bundle_id", "isbn", "synced_at"}
    must_not = {"product_type", "bundle_key", "coupang_sale_price", "winner_status", "upload_method", "last_checked_at"}

    for col in must_have:
        status = "OK" if col in listing_cols else "MISSING"
        print(f"   listings.{col}: [{status}]")

    for col in must_not:
        if col in listing_cols:
            print(f"   listings.{col}: [WARN] 삭제되지 않은 컬럼!")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="DB V3 초기화")
    parser.add_argument("--drop", action="store_true", help="기존 테이블 삭제 후 재생성")
    parser.add_argument("--seed", action="store_true", help="출판사 시딩")
    parser.add_argument("--verify", action="store_true", help="스키마 검증만")
    args = parser.parse_args()

    if args.verify:
        verify_schema()
        return

    if args.drop:
        confirm = input("\n[WARNING] 모든 데이터가 삭제됩니다. 계속하시겠습니까? (yes/no): ").strip()
        if confirm != "yes":
            print("취소됨")
            return

    init_database(drop_first=args.drop)

    if args.seed:
        init_publishers()

    verify_schema()

    print("\n" + "=" * 60)
    print("  초기화 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
