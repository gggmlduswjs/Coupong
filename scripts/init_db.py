"""데이터베이스 초기화 스크립트"""
import sys
from pathlib import Path

# 프로젝트 루트를 파이썬 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import Base, engine, init_db
from app.models import (
    Account,
    KyoboProduct,
    Product,
    Listing,
    Sales,
    AnalysisResult,
    Task
)


def main():
    """DB 테이블 생성"""
    print("Initializing database...")

    # 모든 테이블 생성
    init_db()

    print("Database tables created successfully!")
    print("\nCreated tables:")
    for table in Base.metadata.sorted_tables:
        print(f"  - {table.name}")


if __name__ == "__main__":
    main()
