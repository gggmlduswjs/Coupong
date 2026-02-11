import sqlite3
conn = sqlite3.connect('coupang_auto.db')
c = conn.cursor()

total = c.execute('SELECT COUNT(*) FROM listings').fetchone()[0]
print(f'total listings: {total}')

null_sp = c.execute('SELECT COUNT(*) FROM listings WHERE sale_price IS NULL').fetchone()[0]
zero_sp = c.execute('SELECT COUNT(*) FROM listings WHERE sale_price = 0').fetchone()[0]
has_sp = c.execute('SELECT COUNT(*) FROM listings WHERE sale_price > 0').fetchone()[0]
print(f'sale_price NULL: {null_sp}')
print(f'sale_price = 0: {zero_sp}')
print(f'sale_price > 0: {has_sp}')

print()
print('--- sample (5) ---')
rows = c.execute('SELECT product_name, sale_price, original_price, coupang_status FROM listings LIMIT 5').fetchall()
for r in rows:
    name = (r[0] or '?')[:40]
    print(f'  {name} | sale={r[1]} | orig={r[2]} | st={r[3]}')

print()
print('--- coupang_status ---')
for r in c.execute('SELECT coupang_status, COUNT(*) FROM listings GROUP BY coupang_status').fetchall():
    print(f'  {r[0]}: {r[1]}')

print()
print('--- product type (by product_id/bundle_id) ---')
for r in c.execute('''
    SELECT
        CASE
            WHEN bundle_id IS NOT NULL THEN 'bundle'
            WHEN product_id IS NOT NULL THEN 'single'
            ELSE 'unknown'
        END AS ptype,
        COUNT(*)
    FROM listings GROUP BY ptype
''').fetchall():
    print(f'  {r[0]}: {r[1]}')

conn.close()
