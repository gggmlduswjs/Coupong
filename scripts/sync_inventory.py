"""
가격/재고 자동 업데이트
======================
DB 목표가격과 쿠팡 라이브 가격을 비교하여 차이 시 자동 업데이트.
재고 부족 시 자동 리필.

사용법:
    python scripts/sync_inventory.py                     # 전체 계정
    python scripts/sync_inventory.py --account 007-book  # 특정 계정
    python scripts/sync_inventory.py --dry-run            # 변경 없이 확인만
    python scripts/sync_inventory.py --stock 15           # 리필 재고 수량 지정
    python scripts/sync_inventory.py --threshold 5        # 재고 부족 기준 변경
"""
import os
import sys
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, List

from sqlalchemy import create_engine, text, inspect

# 프로젝트 루트
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
from app.constants import WING_ACCOUNT_ENV_MAP, DEFAULT_STOCK, LOW_STOCK_THRESHOLD
from app.services.wing_sync_base import get_accounts, create_wing_client
from app.services.transaction_manager import atomic_operation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class InventorySync:
    """가격/재고 동기화 엔진"""

    # inventory_sync_log 테이블 DDL
    CREATE_LOG_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS inventory_sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id INTEGER NOT NULL REFERENCES listings(id),
        action VARCHAR(20) NOT NULL,
        old_price INTEGER,
        new_price INTEGER,
        old_quantity INTEGER,
        new_quantity INTEGER,
        success BOOLEAN DEFAULT 1,
        error_message TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """

    # listings 테이블에 추가할 컬럼
    LISTING_NEW_COLS = {
        "vendor_item_id": "VARCHAR(50)",
        "coupang_sale_price": "INTEGER DEFAULT 0",
        "stock_quantity": "INTEGER DEFAULT 10",
    }

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(ROOT / "coupang_auto.db")
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 30}
        )
        # SQLite WAL 모드 + busy_timeout (동시 접근 허용)
        from sqlalchemy import event as _sa_event
        @_sa_event.listens_for(self.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA busy_timeout=30000")
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except Exception:
                pass
            cursor.close()
        self._ensure_tables()
        self._migrate_listing_columns()

    def _ensure_tables(self):
        """동기화 로그 테이블 생성"""
        with self.engine.connect() as conn:
            conn.execute(text(self.CREATE_LOG_TABLE_SQL))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_inv_log_listing ON inventory_sync_log(listing_id)"
            ))
            conn.commit()
        logger.info("inventory_sync_log 테이블 확인 완료")

    def _migrate_listing_columns(self):
        """listings 테이블에 새 컬럼 추가 (기존 DB 호환)"""
        try:
            inspector = inspect(self.engine)
            existing_cols = {col["name"] for col in inspector.get_columns("listings")}
        except Exception:
            return  # 테이블 아직 없음

        with self.engine.connect() as conn:
            for col_name, col_type in self.LISTING_NEW_COLS.items():
                if col_name not in existing_cols:
                    conn.execute(text(
                        f"ALTER TABLE listings ADD COLUMN {col_name} {col_type}"
                    ))
                    logger.info(f"  컬럼 추가: listings.{col_name}")
            conn.commit()

    def _get_accounts(self, account_name: str = None) -> list:
        """WING API 활성 계정 조회 (SQL 인젝션 방지)"""
        return get_accounts(self.engine, account_name)

    def _create_client(self, account: dict) -> CoupangWingClient:
        """계정 정보로 WING 클라이언트 생성"""
        return create_wing_client(account)

    def _log_action(self, conn, listing_id: int, action: str,
                    old_price=None, new_price=None,
                    old_qty=None, new_qty=None,
                    success=True, error_msg=None):
        """동기화 로그 기록"""
        conn.execute(text("""
            INSERT INTO inventory_sync_log
            (listing_id, action, old_price, new_price, old_quantity, new_quantity, success, error_message)
            VALUES (:lid, :action, :op, :np, :oq, :nq, :ok, :err)
        """), {
            "lid": listing_id, "action": action,
            "op": old_price, "np": new_price,
            "oq": old_qty, "nq": new_qty,
            "ok": 1 if success else 0, "err": error_msg,
        })

    def sync_account(self, account: dict, default_stock: int = DEFAULT_STOCK,
                     threshold: int = LOW_STOCK_THRESHOLD,
                     dry_run: bool = False) -> dict:
        """
        단일 계정의 가격/재고 동기화

        2단계 조회:
        1) list_products() → sellerProductId 목록 수집 + DB 매칭
        2) 매칭된 것만 get_product() → vendorItemId/salePrice 상세 조회

        Returns:
            {account, total_checked, price_updated, stock_refilled,
             vendor_id_backfilled, errors, status_updated}
        """
        import re

        account_id = account["id"]
        account_name = account["account_name"]
        client = self._create_client(account)

        result = {
            "account": account_name,
            "total_checked": 0,
            "price_updated": 0,
            "stock_refilled": 0,
            "vendor_id_backfilled": 0,
            "status_updated": 0,
            "errors": 0,
        }

        logger.info(f"\n{'='*50}")
        logger.info(f"재고/가격 동기화: {account_name}")
        logger.info(f"{'='*50}")

        # API 연결 테스트
        if not client.test_connection():
            logger.error(f"  [{account_name}] API 연결 실패")
            return result

        # ── Step 1: 상품 목록 조회 → DB 매칭 ──
        try:
            products = client.list_products(max_per_page=50)
        except CoupangWingError as e:
            logger.error(f"  [{account_name}] 상품 목록 조회 실패: {e}")
            return result

        logger.info(f"  [{account_name}] {len(products)}개 상품 조회")

        # 상태 매핑
        status_map = {
            "판매중": "active", "승인완료": "active", "APPROVE": "active",
            "판매중지": "paused", "SUSPEND": "paused",
            "품절": "sold_out", "SOLDOUT": "sold_out",
            "승인반려": "rejected", "삭제": "deleted", "DELETE": "deleted",
            "승인대기": "pending",
        }

        # DB 매칭 대상 수집
        matched_products = []  # (seller_product_id, product_name, coupang_status, listing_row)

        with self.engine.connect() as conn:
            for product_data in products:
                seller_product_id = str(product_data.get("sellerProductId", ""))
                product_name = product_data.get("sellerProductName", "")
                status_name = product_data.get("statusName", product_data.get("status", ""))
                coupang_status = status_map.get(status_name, "pending")

                # DB listing 매칭 (coupang_product_id)
                listing_row = None
                if seller_product_id:
                    listing_row = conn.execute(text(
                        "SELECT id, sale_price, coupang_sale_price, stock_quantity, "
                        "vendor_item_id, coupang_status, product_id "
                        "FROM listings WHERE account_id = :aid AND coupang_product_id = :cpid LIMIT 1"
                    ), {"aid": account_id, "cpid": seller_product_id}).mappings().first()

                if listing_row:
                    matched_products.append((seller_product_id, product_name, coupang_status, dict(listing_row)))

            # VID 있는/없는 분리
            need_detail = [m for m in matched_products if not (m[3].get("vendor_item_id") or "")]
            have_vid = [m for m in matched_products if (m[3].get("vendor_item_id") or "")]

            logger.info(
                f"  [{account_name}] DB 매칭: {len(matched_products)}/{len(products)}개 "
                f"(VID 있음 {len(have_vid)}, 상세조회 필요 {len(need_detail)})"
            )

            # ── Step 2: 상세 조회 → 가격/재고 동기화 ──
            # VID 있는 것도 처리하되 상세 조회는 VID 없는 것만
            all_targets = have_vid + need_detail

            for idx, (seller_product_id, product_name, coupang_status, listing) in enumerate(all_targets):
                result["total_checked"] += 1

                listing_id = listing["id"]
                db_target_price = listing["sale_price"] or 0
                db_coupang_price = listing["coupang_sale_price"] or 0
                db_stock = listing["stock_quantity"] if listing["stock_quantity"] is not None else default_stock
                db_vid = listing["vendor_item_id"] or ""
                db_status = listing["coupang_status"] or ""
                product_id = listing["product_id"]

                vid = db_vid
                live_price = db_coupang_price

                # VID 없으면 상세 조회 필수
                if not db_vid:
                    try:
                        detail = client.get_product(int(seller_product_id))
                        detail_data = detail.get("data", detail)
                        items = detail_data.get("items", [])
                        if items:
                            item = items[0]
                            vid = str(item.get("vendorItemId", ""))
                            live_price = int(item.get("salePrice", 0) or 0)
                    except CoupangWingError as e:
                        logger.warning(f"  상세 조회 실패: {product_name[:30]} — {e}")
                        result["errors"] += 1
                        continue

                    if idx % 100 == 0 and idx > 0:
                        logger.info(f"  [{account_name}] 상세 조회 진행: {idx}/{len(need_detail)}")
                        conn.commit()  # 중간 커밋

                # 목표가격 결정: products.sale_price → listing.sale_price (폴백)
                target_price = db_target_price
                if product_id:
                    prod_row = conn.execute(text(
                        "SELECT sale_price FROM products WHERE id = :pid LIMIT 1"
                    ), {"pid": product_id}).mappings().first()
                    if prod_row and prod_row["sale_price"]:
                        target_price = prod_row["sale_price"]

                # vendor_item_id 백필
                if vid and vid != db_vid:
                    conn.execute(text(
                        "UPDATE listings SET vendor_item_id = :vid WHERE id = :lid"
                    ), {"vid": vid, "lid": listing_id})
                    result["vendor_id_backfilled"] += 1

                # coupang_sale_price 업데이트 (라이브 가격 기록)
                if live_price and live_price != db_coupang_price:
                    conn.execute(text(
                        "UPDATE listings SET coupang_sale_price = :price WHERE id = :lid"
                    ), {"price": live_price, "lid": listing_id})

                # 쿠팡 상태 변경 반영
                if coupang_status != db_status:
                    conn.execute(text(
                        "UPDATE listings SET coupang_status = :st, last_checked_at = :now WHERE id = :lid"
                    ), {"st": coupang_status, "lid": listing_id, "now": datetime.utcnow().isoformat()})
                    result["status_updated"] += 1
                    logger.info(f"  상태 변경: listing#{listing_id} {db_status} → {coupang_status}")

                # 가격/재고 업데이트 판단
                need_price_update = (target_price > 0 and live_price > 0 and target_price != live_price)
                need_stock_refill = (db_stock <= threshold)

                if not need_price_update and not need_stock_refill:
                    continue

                # 활성 상태가 아니면 업데이트 불가
                if coupang_status != "active":
                    continue

                # vendor_item_id 없으면 API 호출 불가
                effective_vid = vid or db_vid
                if not effective_vid:
                    logger.warning(f"  vendor_item_id 없음: listing#{listing_id} ({product_name[:30]})")
                    continue

                new_price = target_price if need_price_update else live_price
                new_qty = default_stock if need_stock_refill else db_stock

                action_parts = []
                if need_price_update:
                    action_parts.append(f"가격 {live_price:,}→{new_price:,}")
                if need_stock_refill:
                    action_parts.append(f"재고 {db_stock}→{new_qty}")
                action_desc = " + ".join(action_parts)

                if dry_run:
                    logger.info(f"  [DRY-RUN] {product_name[:40]} | {action_desc}")
                    if need_price_update:
                        result["price_updated"] += 1
                    if need_stock_refill:
                        result["stock_refilled"] += 1
                    continue

                # API 호출
                try:
                    api_result = client.update_inventory(
                        vendor_item_id=int(effective_vid),
                        quantity=new_qty,
                        price=new_price,
                    )

                    # 응답 확인 (쿠팡은 HTTP 200에서도 에러 반환 가능)
                    if isinstance(api_result, dict) and api_result.get("code") == "ERROR":
                        raise CoupangWingError("ERROR", api_result.get("message", "알 수 없는 오류"))

                    # 성공 - DB 업데이트
                    conn.execute(text(
                        "UPDATE listings SET coupang_sale_price = :price, stock_quantity = :qty, "
                        "last_checked_at = :now WHERE id = :lid"
                    ), {"price": new_price, "qty": new_qty, "lid": listing_id,
                        "now": datetime.utcnow().isoformat()})

                    if need_price_update:
                        result["price_updated"] += 1
                        self._log_action(conn, listing_id, "price_update",
                                         old_price=live_price, new_price=new_price)
                    if need_stock_refill:
                        result["stock_refilled"] += 1
                        self._log_action(conn, listing_id, "stock_refill",
                                         old_qty=db_stock, new_qty=new_qty)

                    logger.info(f"  OK {product_name[:40]} | {action_desc}")

                except (CoupangWingError, Exception) as e:
                    result["errors"] += 1
                    self._log_action(conn, listing_id, "error",
                                     old_price=live_price, new_price=new_price,
                                     old_qty=db_stock, new_qty=new_qty,
                                     success=False, error_msg=str(e))
                    logger.error(f"  FAIL {product_name[:40]} | {action_desc} | 오류: {e}")

            conn.commit()

        logger.info(
            f"  [{account_name}] 완료: 확인 {result['total_checked']}, "
            f"가격변경 {result['price_updated']}, 재고리필 {result['stock_refilled']}, "
            f"VID백필 {result['vendor_id_backfilled']}, 오류 {result['errors']}"
        )
        return result

    def sync_all(self, account_name: str = None, dry_run: bool = False,
                 default_stock: int = DEFAULT_STOCK,
                 threshold: int = LOW_STOCK_THRESHOLD,
                 progress_callback: Callable = None) -> List[dict]:
        """
        전체 계정 가격/재고 동기화

        Args:
            account_name: 특정 계정만 (None=전체)
            dry_run: True면 변경 없이 확인만
            default_stock: 리필 시 재고 수량
            threshold: 재고 부족 기준
            progress_callback: 진행 콜백 (current, total, message)

        Returns:
            계정별 결과 리스트
        """
        accounts = self._get_accounts(account_name)
        if not accounts:
            logger.warning("WING API 활성화된 계정이 없습니다.")
            return []

        logger.info(f"재고/가격 동기화: {len(accounts)}개 계정 {'[DRY-RUN]' if dry_run else ''}")

        results = []
        for i, account in enumerate(accounts):
            if progress_callback:
                progress_callback(i, len(accounts),
                                  f"{account['account_name']} 동기화 중...")

            result = self.sync_account(
                account,
                default_stock=default_stock,
                threshold=threshold,
                dry_run=dry_run,
            )
            results.append(result)

        if progress_callback:
            progress_callback(len(accounts), len(accounts), "동기화 완료!")

        # 결과 요약
        total_checked = sum(r["total_checked"] for r in results)
        total_price = sum(r["price_updated"] for r in results)
        total_stock = sum(r["stock_refilled"] for r in results)
        total_vid = sum(r["vendor_id_backfilled"] for r in results)
        total_err = sum(r["errors"] for r in results)
        logger.info(
            f"전체 완료: 확인 {total_checked}, 가격변경 {total_price}, "
            f"재고리필 {total_stock}, VID백필 {total_vid}, 오류 {total_err}"
        )

        return results


def main():
    parser = argparse.ArgumentParser(description="가격/재고 자동 업데이트")
    parser.add_argument("--account", type=str, default=None, help="특정 계정명 (기본: 전체)")
    parser.add_argument("--dry-run", action="store_true", help="변경 없이 확인만")
    parser.add_argument("--stock", type=int, default=DEFAULT_STOCK, help=f"리필 재고 수량 (기본: {DEFAULT_STOCK})")
    parser.add_argument("--threshold", type=int, default=LOW_STOCK_THRESHOLD, help=f"재고 부족 기준 (기본: {LOW_STOCK_THRESHOLD})")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  가격/재고 자동 업데이트")
    print(f"  시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.dry_run:
        print("  [DRY-RUN] 변경 없이 확인만 합니다")
    print("=" * 60)

    syncer = InventorySync()
    results = syncer.sync_all(
        account_name=args.account,
        dry_run=args.dry_run,
        default_stock=args.stock,
        threshold=args.threshold,
    )

    # 리포트
    print("\n" + "=" * 60)
    print("  동기화 결과")
    print("=" * 60)
    for r in results:
        print(f"  {r['account']:12s} | 확인 {r['total_checked']:4d} | "
              f"가격 {r['price_updated']:3d} | 재고 {r['stock_refilled']:3d} | "
              f"VID {r['vendor_id_backfilled']:3d} | 오류 {r['errors']:3d}")
    print("=" * 60)

    total_changes = sum(r["price_updated"] + r["stock_refilled"] for r in results)
    print(f"\n  총 변경: {total_changes}건")


if __name__ == "__main__":
    main()
