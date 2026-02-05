"""revenue_history 테이블 상태 확인"""
import sqlite3
import sys
from pathlib import Path

db_path = Path(__file__).parent.parent / "coupang_auto.db"
conn = sqlite3.connect(str(db_path))
c = conn.cursor()

# 테이블 존재 확인
tables = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='revenue_history'").fetchall()
print(f"revenue_history 테이블: {'있음' if tables else '없음'}")

if not tables:
    print("테이블이 없습니다. 'python scripts/sync_revenue.py' 실행 필요")
    sys.exit(0)

cnt = c.execute("SELECT COUNT(*) FROM revenue_history").fetchone()[0]
print(f"총 레코드: {cnt}")

if cnt == 0:
    print("데이터가 없습니다. '매출 동기화' 버튼을 누르거나 sync_revenue.py 실행 필요")
    sys.exit(0)

# 계정별 건수
rows = c.execute("""
    SELECT a.account_name, COUNT(*) as cnt,
           MIN(r.recognition_date) as min_date,
           MAX(r.recognition_date) as max_date,
           SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE 0 END) as total_sale,
           SUM(CASE WHEN r.sale_type='REFUND' THEN r.sale_amount ELSE 0 END) as total_refund
    FROM revenue_history r
    JOIN accounts a ON r.account_id = a.id
    GROUP BY r.account_id
""").fetchall()

print(f"\n{'계정':12s} {'건수':>6s} {'시작일':12s} {'종료일':12s} {'매출':>12s} {'환불':>10s}")
print("-" * 70)
for r in rows:
    print(f"{r[0]:12s} {r[1]:6d} {r[2]:12s} {r[3]:12s} {r[4]:>12,} {r[5]:>10,}")

# 샘플 데이터
print("\n=== 최근 5건 샘플 ===")
samples = c.execute("""
    SELECT order_id, sale_type, recognition_date, product_name, quantity, sale_amount, settlement_amount
    FROM revenue_history ORDER BY id DESC LIMIT 5
""").fetchall()
for s in samples:
    name = (s[3] or "")[:30]
    print(f"  주문{s[0]} | {s[1]:6s} | {s[2]} | {name:30s} | 수량{s[4]} | 매출{s[5]:,} | 정산{s[6]:,}")

# listing 매칭률
matched = c.execute("SELECT COUNT(*) FROM revenue_history WHERE listing_id IS NOT NULL").fetchone()[0]
print(f"\nlisting 매칭: {matched}/{cnt} ({matched*100//cnt}%)")

conn.close()
