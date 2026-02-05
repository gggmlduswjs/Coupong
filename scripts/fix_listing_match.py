"""기존 revenue_history의 listing_id를 product_name으로 재매칭"""
import sqlite3
from pathlib import Path

db_path = Path(__file__).parent.parent / "coupang_auto.db"
conn = sqlite3.connect(str(db_path))

updated = conn.execute("""
    UPDATE revenue_history
    SET listing_id = (
        SELECT l.id FROM listings l
        WHERE l.account_id = revenue_history.account_id
          AND l.product_name = revenue_history.product_name
        LIMIT 1
    )
    WHERE listing_id IS NULL
      AND product_name IS NOT NULL
""").rowcount
conn.commit()

total = conn.execute("SELECT COUNT(*) FROM revenue_history").fetchone()[0]
matched = conn.execute("SELECT COUNT(*) FROM revenue_history WHERE listing_id IS NOT NULL").fetchone()[0]
print(f"업데이트: {updated}건")
print(f"매칭 결과: {matched}/{total} ({matched*100//total if total else 0}%)")

conn.close()
