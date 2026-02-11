#!/usr/bin/env python3
"""ISBN 통계 확인"""
import sys
import io
from pathlib import Path

# Windows cp949 인코딩 대응
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# 프로젝트 루트 경로 추가
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.database import engine
from sqlalchemy import text

conn = engine.connect()

total = conn.execute(text('SELECT COUNT(*) FROM listings')).scalar()
with_isbn = conn.execute(text("SELECT COUNT(*) FROM listings WHERE isbn IS NOT NULL AND isbn != ''")).scalar()

print(f'총 상품: {total:,}개')
print(f'ISBN 보유: {with_isbn:,}개 ({with_isbn/total*100:.2f}%)')
print(f'ISBN 없음: {total-with_isbn:,}개')

conn.close()
