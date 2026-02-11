"""
통합 ISBN 채우기 CLI
===================
app/services/isbn_filler.py의 CLI 래퍼.

사용법:
    python scripts/fill_isbn.py                              # 전체 (wing→books→aladin)
    python scripts/fill_isbn.py --strategy wing              # WING API만
    python scripts/fill_isbn.py --strategy books,aladin      # books + aladin
    python scripts/fill_isbn.py --account 007-book           # 특정 계정
    python scripts/fill_isbn.py --limit 100                  # 최대 100건
"""
import sys
import os
import argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from app.database import engine
from app.services.isbn_filler import ISBNFillerService


def main():
    parser = argparse.ArgumentParser(description="통합 ISBN 채우기")
    parser.add_argument("--strategy", type=str, default="wing,books,aladin",
                        help="실행할 전략 (쉼표 구분: wing,books,aladin)")
    parser.add_argument("--account", type=str, default=None,
                        help="특정 계정만 (예: 007-book)")
    parser.add_argument("--limit", type=int, default=0,
                        help="최대 처리 건수 (기본: 무제한)")
    args = parser.parse_args()

    strategies = [s.strip() for s in args.strategy.split(",") if s.strip()]

    svc = ISBNFillerService(engine)
    results = svc.run(strategies=strategies, account=args.account, limit=args.limit)

    print(f"\n최종: {results.get('total', {})}")


if __name__ == "__main__":
    main()
