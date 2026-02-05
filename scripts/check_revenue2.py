"""revenue_history 문제 진단"""
import sqlite3
from pathlib import Path

db_path = Path(__file__).parent.parent / "coupang_auto.db"
conn = sqlite3.connect(str(db_path))
c = conn.cursor()

print("=== 문제 1: 날짜 범위 ===")
date_range = c.execute("SELECT MIN(recognition_date), MAX(recognition_date) FROM revenue_history").fetchone()
print(f"데이터 범위: {date_range[0]} ~ {date_range[1]}")
print(f"오늘: 2026-02-05")
print(f"-> 1/7 이후 데이터 없음 = 재동기화 필요\n")

print("=== 문제 2: listing 매칭 0% 진단 ===")
# revenue의 product_id 샘플
rev_pids = c.execute("""
    SELECT DISTINCT product_id FROM revenue_history
    WHERE product_id IS NOT NULL LIMIT 10
""").fetchall()
print(f"revenue product_id 샘플: {[r[0] for r in rev_pids]}")

# listings의 coupang_product_id 샘플
lst_pids = c.execute("""
    SELECT DISTINCT coupang_product_id FROM listings
    WHERE coupang_product_id IS NOT NULL LIMIT 10
""").fetchall()
print(f"listings coupang_product_id 샘플: {[r[0] for r in lst_pids]}")

# 타입 확인
rev_type = c.execute("SELECT typeof(product_id) FROM revenue_history WHERE product_id IS NOT NULL LIMIT 1").fetchone()
lst_type = c.execute("SELECT typeof(coupang_product_id) FROM listings WHERE coupang_product_id IS NOT NULL LIMIT 1").fetchone()
print(f"revenue product_id 타입: {rev_type[0] if rev_type else 'N/A'}")
print(f"listings coupang_product_id 타입: {lst_type[0] if lst_type else 'N/A'}")

# 교차 매칭 시도
match_test = c.execute("""
    SELECT COUNT(*) FROM revenue_history r
    WHERE EXISTS (
        SELECT 1 FROM listings l
        WHERE l.coupang_product_id = CAST(r.product_id AS TEXT)
          AND l.account_id = r.account_id
    )
""").fetchone()[0]
print(f"\nCAST 매칭 결과: {match_test}건")

# vendor_item_id 기반 매칭도 시도
match2 = c.execute("""
    SELECT COUNT(*) FROM revenue_history r
    WHERE EXISTS (
        SELECT 1 FROM listings l
        WHERE l.coupang_product_id = CAST(r.vendor_item_id AS TEXT)
          AND l.account_id = r.account_id
    )
""").fetchone()[0]
print(f"vendor_item_id 매칭: {match2}건")

# product_name 기반 매칭
match3 = c.execute("""
    SELECT COUNT(*) FROM revenue_history r
    WHERE EXISTS (
        SELECT 1 FROM listings l
        WHERE l.product_name = r.product_name
          AND l.account_id = r.account_id
    )
""").fetchone()[0]
print(f"product_name 매칭: {match3}건")

# 전체 listings 수
total_listings = c.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
print(f"\n총 listings: {total_listings}건")

conn.close()
