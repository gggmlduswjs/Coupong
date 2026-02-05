"""
판매가 일괄 채우기
==================
list_products API에 가격이 없어서 0원인 listings를
개별 상품 상세 조회로 가격을 채움 (1회성 배치)

사용법:
    python scripts/fill_prices.py              # 전체 실행
    python scripts/fill_prices.py --limit 100  # 100개만 테스트
    python scripts/fill_prices.py --account 007-book  # 특정 계정만
"""
import sys
import os
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.database import init_db
from app.models.account import Account
from app.models.listing import Listing
from scripts.sync_coupang_products import create_wing_client
from app.api.coupang_wing_client import CoupangWingError

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

DB_TIMEOUT = 30


def _safe_commit(db, retries=3):
    """SQLite lock 대비 재시도 커밋"""
    for attempt in range(retries):
        try:
            db.commit()
            return
        except Exception:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                raise


def fill_prices(account_name=None, limit=0):
    init_db()
    # timeout 설정으로 대시보드 동시접근 충돌 방지
    db_url = settings.database_url
    connect_args = {"check_same_thread": False, "timeout": DB_TIMEOUT} if "sqlite" in db_url else {}
    engine = create_engine(db_url, connect_args=connect_args, echo=False)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()

    try:
        # 대상 계정 조회
        acct_query = db.query(Account).filter(
            Account.is_active == True,
            Account.wing_api_enabled == True,
        )
        if account_name:
            acct_query = acct_query.filter(Account.account_name == account_name)
        accounts = acct_query.all()

        if not accounts:
            print("WING API 활성 계정 없음")
            return

        total_updated = 0
        total_failed = 0
        total_skipped = 0

        for account in accounts:
            # 이 계정에서 sale_price = 0인 listings
            q = db.query(Listing).filter(
                Listing.account_id == account.id,
                Listing.sale_price.in_([0, None]),
                Listing.coupang_product_id.isnot(None),
            )
            if limit > 0:
                q = q.limit(limit)
            listings = q.all()

            if not listings:
                print(f"  {account.account_name}: 채울 항목 없음")
                continue

            print(f"\n{'='*50}")
            print(f"  {account.account_name}: {len(listings)}개 가격 조회 시작")
            print(f"  예상 소요: ~{len(listings) * 0.15:.0f}초 ({len(listings) * 0.15 / 60:.1f}분)")
            print(f"{'='*50}")

            try:
                client = create_wing_client(account)
            except ValueError as e:
                print(f"  API 클라이언트 생성 실패: {e}")
                continue

            updated = 0
            failed = 0
            skipped = 0
            start = time.time()
            commit_batch = 0

            for i, listing in enumerate(listings):
                spid = listing.coupang_product_id
                if not spid:
                    skipped += 1
                    continue

                try:
                    detail = client.get_product(int(spid))
                    data = detail.get("data", detail)

                    items = data.get("items", [])
                    if items:
                        sp = items[0].get("salePrice", 0) or 0
                        op = items[0].get("originalPrice", 0) or 0
                        if sp > 0:
                            listing.sale_price = sp
                            listing.original_price = op
                            updated += 1
                        else:
                            skipped += 1
                    else:
                        skipped += 1

                except CoupangWingError as e:
                    failed += 1
                    if "RATE_LIMIT" in str(e.code):
                        time.sleep(1)
                except Exception as e:
                    failed += 1

                # 100개마다 커밋 + 진행률
                commit_batch += 1
                if commit_batch >= 100:
                    _safe_commit(db)
                    commit_batch = 0
                    elapsed = time.time() - start
                    speed = (i + 1) / elapsed if elapsed > 0 else 0
                    remaining = (len(listings) - i - 1) / speed if speed > 0 else 0
                    print(f"  [{i+1}/{len(listings)}] 업데이트 {updated}, 실패 {failed}, 스킵 {skipped} | {remaining:.0f}초 남음")

            _safe_commit(db)
            elapsed = time.time() - start

            print(f"\n  {account.account_name} 완료: 업데이트 {updated}, 실패 {failed}, 스킵 {skipped} ({elapsed:.0f}초)")
            total_updated += updated
            total_failed += failed
            total_skipped += skipped

        print(f"\n{'='*50}")
        print(f"  전체 완료: 업데이트 {total_updated}, 실패 {total_failed}, 스킵 {total_skipped}")
        print(f"{'='*50}")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="판매가 일괄 채우기")
    parser.add_argument("--account", type=str, help="특정 계정만")
    parser.add_argument("--limit", type=int, default=0, help="계정당 최대 처리 수")
    args = parser.parse_args()
    fill_prices(account_name=args.account, limit=args.limit)
