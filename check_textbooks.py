import sqlite3
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

conn = sqlite3.connect('coupang_auto_backup.db')
cursor = conn.cursor()

keywords = ['마더텅', '자이스토리', '오투', '완자', '쎈', '한끝', '개념', '풍산자', '일품', '수능특강']
total = 0

for kw in keywords:
    cursor.execute('SELECT COUNT(*) FROM books WHERE title LIKE ?', (f'%{kw}%',))
    count = cursor.fetchone()[0]
    total += count
    print(f'{kw:10s}: {count:4d}개')

print(f'\n주요 교재 합계: {total:,}개')

cursor.execute('SELECT COUNT(*) FROM books')
print(f'Books 테이블 전체: {cursor.fetchone()[0]:,}개')
print(f'교재 비율: {total/cursor.execute("SELECT COUNT(*) FROM books").fetchone()[0]*100:.1f}%')

conn.close()
