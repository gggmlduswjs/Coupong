import sqlite3
conn = sqlite3.connect('coupang_auto.db')
c = conn.cursor()
total = c.execute('SELECT COUNT(*) FROM listings').fetchone()[0]
zero = c.execute('SELECT COUNT(*) FROM listings WHERE sale_price = 0 OR sale_price IS NULL').fetchone()[0]
filled = c.execute('SELECT COUNT(*) FROM listings WHERE sale_price > 0').fetchone()[0]
print(f'전체: {total}')
print(f'가격 채움: {filled}')
print(f'아직 0원: {zero}')
print(f'진행률: {filled/total*100:.1f}%')
conn.close()
