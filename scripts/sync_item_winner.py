"""
아이템 위너 동기화
==================
listings 테이블의 active 상품에 대해 WING API get_product()를 호출하여
아이템 위너(Buy Box) 여부를 확인하고 DB에 저장.

사용법:
    python scripts/sync_item_winner.py                    # 전체 active 상품 위너 체크
    python scripts/sync_item_winner.py --account 007-bm   # 특정 계정만
    python scripts/sync_item_winner.py --dry-run           # API 응답 확인만 (1건)
    python scripts/sync_item_winner.py --force             # 이미 체크된 것도 재확인
    python scripts/sync_item_winner.py --stale-hours 12    # 12시간 이상 지난 것만
"""
import sys
import os
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 루트 설정
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.database import SessionLocal, init_db, engine
from app.models.account import Account
from app.models.listing import Listing
from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def _safe_commit(db):
    """DB 커밋"""
    db.commit()


def create_wing_client(account: Account) -> CoupangWingClient:
    """Account 모델에서 WING API 클라이언트 생성"""
    if not account.has_wing_api:
        raise ValueError(f"{account.account_name}: WING API 정보가 없습니다")
    return CoupangWingClient(
        vendor_id=account.vendor_id,
        access_key=account.wing_access_key,
        secret_key=account.wing_secret_key,
    )


def check_winner_field_exists(client: CoupangWingClient, seller_product_id: str) -> dict:
    """
    단건 API 호출로 winner 필드 존재 여부 확인 (dry-run용)

    Returns:
        {"has_winner": bool, "winner_value": any, "has_item_id": bool, "raw_item": dict}
    """
    try:
        result = client.get_product(int(seller_product_id))
        data = result.get("data", result) if isinstance(result, dict) else result
        items = data.get("items", [])
        if not items:
            return {"has_winner": False, "winner_value": None, "has_item_id": False, "raw_item": {}}

        item = items[0]
        winner_value = item.get("winner")
        item_id = item.get("itemId")
        return {
            "has_winner": "winner" in item,
            "winner_value": winner_value,
            "has_item_id": item_id is not None,
            "item_id": item_id,
            "raw_item_keys": list(item.keys()),
        }
    except CoupangWingError as e:
        logger.error(f"  API 호출 실패 [{seller_product_id}]: {e}")
        return {"has_winner": False, "winner_value": None, "has_item_id": False, "error": str(e)}


def sync_account_winners(
    db, account: Account, force: bool = False, stale_hours: int = 24,
) -> dict:
    """
    단일 계정의 active 상품에 대해 위너 상태 동기화

    Returns:
        {"total", "winner", "not_winner", "unknown", "error", "skipped"}
    """
    result = {"total": 0, "winner": 0, "not_winner": 0, "unknown": 0, "error": 0, "skipped": 0}

    try:
        client = create_wing_client(account)
    except ValueError as e:
        logger.error(str(e))
        return result

    logger.info(f"\n{'='*50}")
    logger.info(f"위너 체크: {account.account_name}")
    logger.info(f"{'='*50}")

    # active + coupang_product_id 있는 listings
    query = db.query(Listing).filter(
        Listing.account_id == account.id,
        Listing.coupang_status == 'active',
        Listing.coupang_product_id.isnot(None),
    )

    listings = query.all()
    result["total"] = len(listings)

    if not listings:
        logger.info("  active 상품 없음")
        return result

    now = datetime.utcnow()
    stale_cutoff = now - timedelta(hours=stale_hours)

    for i, lst in enumerate(listings, 1):
        # force가 아니면, 최근 체크된 것은 스킵
        if not force and lst.winner_checked_at and lst.winner_checked_at > stale_cutoff:
            result["skipped"] += 1
            continue

        try:
            resp = client.get_product(int(lst.coupang_product_id))
            data = resp.get("data", resp) if isinstance(resp, dict) else resp
            items = data.get("items", [])

            if not items:
                result["unknown"] += 1
                continue

            item = items[0]

            # winner 필드 파싱
            winner_raw = item.get("winner")
            if winner_raw is True:
                lst.winner_status = "winner"
                result["winner"] += 1
            elif winner_raw is False:
                lst.winner_status = "not_winner"
                result["not_winner"] += 1
            else:
                # winner 필드가 없으면 salesStatus로 추정
                lst.winner_status = None
                result["unknown"] += 1

            lst.winner_checked_at = now

            # item_id 저장 (아직 없는 경우)
            item_id = item.get("itemId")
            if item_id and not lst.item_id:
                lst.item_id = str(item_id)

            # vendor_item_id도 갱신
            vid = item.get("vendorItemId")
            if vid and not lst.vendor_item_id:
                lst.vendor_item_id = str(vid)

            # 50건마다 중간 커밋
            if i % 50 == 0:
                _safe_commit(db)
                logger.info(f"    진행: {i}/{len(listings)} (위너:{result['winner']}, 비위너:{result['not_winner']})")

        except CoupangWingError as e:
            result["error"] += 1
            if e.status_code == 429 or "RATE" in str(e.code).upper():
                logger.warning(f"    Rate limit, 2초 대기: {lst.coupang_product_id}")
                time.sleep(2)
            else:
                logger.warning(f"    위너 조회 실패 [{lst.coupang_product_id}]: {e}")
        except Exception as e:
            result["error"] += 1
            logger.warning(f"    위너 조회 오류 [{lst.coupang_product_id}]: {type(e).__name__}: {e}")

    _safe_commit(db)
    logger.info(f"  완료: 위너 {result['winner']}개, 비위너 {result['not_winner']}개, "
                f"미확인 {result['unknown']}개, 에러 {result['error']}개, 스킵 {result['skipped']}개")

    return result


def run_sync(account_names=None, dry_run=False, force=False, stale_hours=24):
    """전체 위너 동기화 실행"""
    print("\n" + "=" * 60)
    print("  아이템 위너 동기화")
    print(f"  시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    init_db()
    db = SessionLocal()

    try:
        # 동기화 대상 계정
        query = db.query(Account).filter(
            Account.is_active == True,
            Account.wing_api_enabled == True,
        )
        if account_names:
            query = query.filter(Account.account_name.in_(account_names))

        accounts = query.all()

        if not accounts:
            print("\n  WING API가 활성화된 계정이 없습니다.")
            return

        print(f"\n  대상: {len(accounts)}개 계정")

        # dry-run: 첫 계정의 첫 active listing 1건만 API 호출
        if dry_run:
            print("\n  [DRY-RUN] API 응답에서 winner 필드 확인")
            for acc in accounts:
                try:
                    client = create_wing_client(acc)
                except ValueError:
                    continue

                sample = db.query(Listing).filter(
                    Listing.account_id == acc.id,
                    Listing.coupang_status == 'active',
                    Listing.coupang_product_id.isnot(None),
                ).first()

                if not sample:
                    print(f"    {acc.account_name}: active 상품 없음")
                    continue

                print(f"\n    계정: {acc.account_name}")
                print(f"    상품: {sample.product_name} (ID: {sample.coupang_product_id})")

                info = check_winner_field_exists(client, sample.coupang_product_id)
                print(f"    winner 필드 존재: {info['has_winner']}")
                print(f"    winner 값: {info['winner_value']}")
                print(f"    itemId 존재: {info.get('has_item_id', False)}")
                print(f"    itemId 값: {info.get('item_id', '-')}")
                if "raw_item_keys" in info:
                    print(f"    item 키 목록: {info['raw_item_keys']}")
                if "error" in info:
                    print(f"    에러: {info['error']}")
                break
            return

        # 실제 동기화
        total = {"total": 0, "winner": 0, "not_winner": 0, "unknown": 0, "error": 0, "skipped": 0}

        for acc in accounts:
            r = sync_account_winners(db, acc, force=force, stale_hours=stale_hours)
            for k in total:
                total[k] += r[k]

        # 결과 요약
        print("\n" + "=" * 60)
        print("  위너 동기화 결과")
        print("=" * 60)
        print(f"  대상: {total['total']}개")
        print(f"  위너: {total['winner']}개")
        print(f"  비위너: {total['not_winner']}개")
        print(f"  미확인: {total['unknown']}개")
        print(f"  에러: {total['error']}개")
        print(f"  스킵: {total['skipped']}개")
        print("=" * 60)

    except Exception as e:
        logger.error(f"위너 동기화 오류: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="아이템 위너 동기화")
    parser.add_argument(
        "--account", nargs="+",
        help="특정 계정만 (예: --account 007-bm)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="API 응답에서 winner 필드 확인만 (1건)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="이미 체크된 것도 재확인"
    )
    parser.add_argument(
        "--stale-hours", type=int, default=24,
        help="재확인 기준 시간 (기본: 24시간)"
    )

    args = parser.parse_args()

    run_sync(
        account_names=args.account,
        dry_run=args.dry_run,
        force=args.force,
        stale_hours=args.stale_hours,
    )


if __name__ == "__main__":
    main()
