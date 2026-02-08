"""
발주서(주문) 동기화 스크립트
============================
WING Ordersheet API → orders 테이블

사용법:
    python scripts/sync_orders.py              # 기본 7일
    python scripts/sync_orders.py --days 30    # 최근 30일
    python scripts/sync_orders.py --account 007-book  # 특정 계정만
    python scripts/sync_orders.py --status ACCEPT      # 특정 상태만
"""
import os
import sys
import json
import argparse
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional, Callable

from sqlalchemy import text

# 프로젝트 루트
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.database import get_engine_for_db

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
from app.services.wing_sync_base import get_accounts, create_wing_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 조회 대상 상태 목록
ORDER_STATUSES = ["ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING", "FINAL_DELIVERY", "NONE_TRACKING"]


class OrderSync:
    """발주서(주문) 동기화 엔진"""

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        shipment_box_id BIGINT NOT NULL,
        order_id BIGINT NOT NULL,
        vendor_item_id BIGINT,
        status VARCHAR(30),
        ordered_at DATETIME,
        paid_at DATETIME,
        orderer_name VARCHAR(100),
        receiver_name VARCHAR(100),
        receiver_addr VARCHAR(500),
        receiver_post_code VARCHAR(10),
        product_id INTEGER,
        seller_product_id INTEGER,
        seller_product_name VARCHAR(500),
        vendor_item_name VARCHAR(500),
        shipping_count INTEGER DEFAULT 0,
        cancel_count INTEGER DEFAULT 0,
        hold_count_for_cancel INTEGER DEFAULT 0,
        sales_price INTEGER DEFAULT 0,
        order_price INTEGER DEFAULT 0,
        discount_price INTEGER DEFAULT 0,
        shipping_price INTEGER DEFAULT 0,
        delivery_company_name VARCHAR(50),
        invoice_number VARCHAR(50),
        shipment_type VARCHAR(20),
        delivered_date DATETIME,
        confirm_date DATETIME,
        refer VARCHAR(50),
        canceled BOOLEAN DEFAULT 0,
        listing_id INTEGER REFERENCES listings(id),
        raw_json TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(account_id, shipment_box_id, vendor_item_id)
    )
    """

    CREATE_INDEXES_SQL = [
        "CREATE INDEX IF NOT EXISTS ix_order_account_date ON orders(account_id, ordered_at)",
        "CREATE INDEX IF NOT EXISTS ix_order_account_status ON orders(account_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_order_order_id ON orders(order_id)",
    ]

    def __init__(self, db_path: str = None):
        self.engine = get_engine_for_db(db_path)
        self._ensure_table()

    def _ensure_table(self):
        """테이블이 없으면 생성"""
        with self.engine.connect() as conn:
            conn.execute(text(self.CREATE_TABLE_SQL))
            for idx_sql in self.CREATE_INDEXES_SQL:
                conn.execute(text(idx_sql))
            conn.commit()
        logger.info("orders 테이블 확인 완료")

    def _get_accounts(self, account_name: str = None) -> list:
        """WING API 활성 계정 목록"""
        return get_accounts(self.engine, account_name)

    def _create_client(self, account: dict) -> CoupangWingClient:
        """계정 정보로 WING 클라이언트 생성"""
        return create_wing_client(account)

    def _parse_datetime(self, dt_str) -> Optional[str]:
        """날짜/시간 문자열 파싱"""
        if not dt_str:
            return None
        if isinstance(dt_str, datetime):
            return dt_str.isoformat()
        # "2026-01-15T10:30:00" 형식
        return str(dt_str)[:19]

    @staticmethod
    def _extract_price(price_val) -> int:
        """v5 가격 Object {currencyCode, units, nanos} 또는 v4 plain int 파싱"""
        if price_val is None:
            return 0
        if isinstance(price_val, dict):
            return int(price_val.get("units", 0) or 0)
        return int(price_val or 0)

    def _match_listing(self, conn, account_id: int, seller_product_id, product_name: str = None) -> Optional[int]:
        """seller_product_id 또는 product_name으로 listings 매칭"""
        # 1차: coupang_product_id 매칭
        if seller_product_id:
            row = conn.execute(text(
                "SELECT id FROM listings WHERE account_id = :aid AND coupang_product_id = :pid LIMIT 1"
            ), {"aid": account_id, "pid": str(seller_product_id)}).fetchone()
            if row:
                return row[0]
        # 2차: product_name 매칭
        if product_name:
            row = conn.execute(text(
                "SELECT id FROM listings WHERE account_id = :aid AND product_name = :name LIMIT 1"
            ), {"aid": account_id, "name": product_name}).fetchone()
            if row:
                return row[0]
        return None

    def _extract_order_items(self, ordersheet: dict) -> List[dict]:
        """
        발주서 응답에서 주문 아이템 추출

        API 응답 구조:
        - shipmentBoxId, orderId, ordererName, ...
        - orderItems: [{vendorItemId, vendorItemName, shippingCount, ...}]
        """
        items = ordersheet.get("orderItems", [])
        if not items:
            # orderItems가 없으면 ordersheet 자체를 아이템으로 처리
            return [ordersheet]
        return items

    def sync_account(self, account: dict, date_from: date, date_to: date,
                     statuses: List[str] = None,
                     progress_callback: Callable = None) -> dict:
        """
        계정 1개의 주문 동기화

        Returns:
            {"account": str, "fetched": int, "upserted": int, "matched": int}
        """
        account_id = account["id"]
        account_name = account["account_name"]
        client = self._create_client(account)

        if statuses is None:
            statuses = ORDER_STATUSES

        logger.info(f"[{account_name}] 주문 동기화 시작: {date_from} ~ {date_to}")

        # 날짜 범위를 31일 윈도우로 분할
        windows = self._split_date_range(date_from, date_to)
        total_fetched = 0
        total_upserted = 0
        total_matched = 0

        for wi, (w_from, w_to) in enumerate(windows):
            for status in statuses:
                logger.info(f"  [{account_name}] 윈도우 {wi+1}/{len(windows)} 상태={status}: {w_from} ~ {w_to}")

                try:
                    ordersheets = client.get_all_ordersheets(w_from, w_to, status=status)
                except CoupangWingError as e:
                    logger.error(f"  [{account_name}] API 오류 ({status}): {e}")
                    continue

                if not ordersheets:
                    continue

                for os_data in ordersheets:
                    shipment_box_id = os_data.get("shipmentBoxId")
                    order_id = os_data.get("orderId")
                    if not shipment_box_id or not order_id:
                        continue

                    order_items = self._extract_order_items(os_data)

                    for item in order_items:
                        total_fetched += 1
                        v_item_id = item.get("vendorItemId") or os_data.get("vendorItemId")

                        # listing 매칭
                        sp_id = item.get("sellerProductId") or os_data.get("sellerProductId")
                        sp_name = item.get("sellerProductName") or os_data.get("sellerProductName", "")

                        # v5 응답: orderer/receiver가 중첩 객체, 가격은 {units, nanos} Object
                        orderer = os_data.get("orderer") or {}
                        receiver = os_data.get("receiver") or {}
                        addr1 = receiver.get("addr1", "") or ""
                        addr2 = receiver.get("addr2", "") or ""
                        receiver_addr = f"{addr1} {addr2}".strip()

                        params = {
                            "account_id": account_id,
                            "shipment_box_id": int(shipment_box_id),
                            "order_id": int(order_id),
                            "vendor_item_id": int(v_item_id) if v_item_id else None,
                            "status": status,
                            "ordered_at": self._parse_datetime(os_data.get("orderedAt")),
                            "paid_at": self._parse_datetime(os_data.get("paidAt")),
                            "orderer_name": orderer.get("name", ""),
                            "receiver_name": receiver.get("name", ""),
                            "receiver_addr": receiver_addr,
                            "receiver_post_code": receiver.get("postCode", ""),
                            "product_id": int(item.get("productId") or 0) or None,
                            "seller_product_id": int(sp_id) if sp_id else None,
                            "seller_product_name": sp_name,
                            "vendor_item_name": item.get("vendorItemName") or "",
                            "shipping_count": int(item.get("shippingCount", 0) or 0),
                            "cancel_count": int(item.get("cancelCount", 0) or 0),
                            "hold_count_for_cancel": int(item.get("holdCountForCancel", 0) or 0),
                            "sales_price": self._extract_price(item.get("salesPrice")),
                            "order_price": self._extract_price(item.get("orderPrice")),
                            "discount_price": self._extract_price(item.get("discountPrice")),
                            "shipping_price": self._extract_price(os_data.get("shippingPrice")),
                            "delivery_company_name": os_data.get("deliveryCompanyName", ""),
                            "invoice_number": os_data.get("invoiceNumber", ""),
                            "shipment_type": os_data.get("shipmentType", ""),
                            "delivered_date": self._parse_datetime(os_data.get("deliveredDate")),
                            "confirm_date": self._parse_datetime(item.get("confirmDate")),
                            "refer": os_data.get("refer", ""),
                            "canceled": bool(item.get("canceled", False)),
                            "listing_id": None,
                            "raw_json": json.dumps(os_data, ensure_ascii=False, default=str)[:5000],
                            "updated_at": datetime.utcnow().isoformat(),
                        }

                        # 건별 커밋 + 재시도 (DB 잠금 방지)
                        for attempt in range(3):
                            try:
                                with self.engine.connect() as conn:
                                    # listing 매칭
                                    listing_id = self._match_listing(conn, account_id, sp_id, sp_name)
                                    if listing_id:
                                        params["listing_id"] = listing_id
                                        total_matched += 1

                                    conn.execute(text("""
                                        INSERT OR REPLACE INTO orders
                                        (account_id, shipment_box_id, order_id, vendor_item_id,
                                         status, ordered_at, paid_at,
                                         orderer_name, receiver_name, receiver_addr, receiver_post_code,
                                         product_id, seller_product_id, seller_product_name, vendor_item_name,
                                         shipping_count, cancel_count, hold_count_for_cancel,
                                         sales_price, order_price, discount_price, shipping_price,
                                         delivery_company_name, invoice_number, shipment_type,
                                         delivered_date, confirm_date,
                                         refer, canceled, listing_id, raw_json, updated_at)
                                        VALUES
                                        (:account_id, :shipment_box_id, :order_id, :vendor_item_id,
                                         :status, :ordered_at, :paid_at,
                                         :orderer_name, :receiver_name, :receiver_addr, :receiver_post_code,
                                         :product_id, :seller_product_id, :seller_product_name, :vendor_item_name,
                                         :shipping_count, :cancel_count, :hold_count_for_cancel,
                                         :sales_price, :order_price, :discount_price, :shipping_price,
                                         :delivery_company_name, :invoice_number, :shipment_type,
                                         :delivered_date, :confirm_date,
                                         :refer, :canceled, :listing_id, :raw_json, :updated_at)
                                    """), params)
                                    conn.commit()
                                total_upserted += 1
                                break
                            except SQLAlchemyError as e:
                                if attempt < 2 and "database is locked" in str(e):
                                    import time
                                    time.sleep(1 + attempt)
                                    continue
                                logger.warning(f"  DB 오류: {e}")
                            except (ValueError, TypeError) as e:
                                logger.warning(f"  데이터 변환 오류: {e}")
                                break

            if progress_callback:
                progress_callback(wi + 1, len(windows),
                                  f"[{account_name}] {wi+1}/{len(windows)} 윈도우 완료 ({total_fetched}건)")

        result = {
            "account": account_name,
            "fetched": total_fetched,
            "upserted": total_upserted,
            "matched": total_matched,
        }
        logger.info(f"[{account_name}] 완료: 조회 {total_fetched}건, 저장 {total_upserted}건, 매칭 {total_matched}건")
        return result

    @staticmethod
    def _split_date_range(date_from: date, date_to: date, window_days: int = 31) -> list:
        """날짜 범위를 window_days 단위 윈도우로 분할"""
        windows = []
        current = date_from
        while current <= date_to:
            end = min(current + timedelta(days=window_days - 1), date_to)
            windows.append((current.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
            current = end + timedelta(days=1)
        return windows

    def sync_all(self, days: int = 7, account_name: str = None,
                 statuses: List[str] = None,
                 progress_callback: Callable = None) -> List[dict]:
        """
        전체 계정 주문 동기화

        Args:
            days: 동기화 기간 (일, 기본 7)
            account_name: 특정 계정만 (None=전체)
            statuses: 조회할 상태 리스트 (None=전체)
            progress_callback: 진행 콜백 (current, total, message)

        Returns:
            계정별 결과 리스트
        """
        accounts = self._get_accounts(account_name)
        if not accounts:
            logger.warning("WING API 활성화된 계정이 없습니다.")
            return []

        date_to = date.today()
        date_from = date_to - timedelta(days=days)

        logger.info(f"주문 동기화: {len(accounts)}개 계정, {date_from} ~ {date_to}")

        results = []
        for i, account in enumerate(accounts):
            if progress_callback:
                progress_callback(i, len(accounts),
                                  f"{account['account_name']} 동기화 중...")

            result = self.sync_account(account, date_from, date_to,
                                       statuses=statuses,
                                       progress_callback=progress_callback)
            results.append(result)

        if progress_callback:
            progress_callback(len(accounts), len(accounts), "동기화 완료!")

        # 결과 요약
        total_f = sum(r["fetched"] for r in results)
        total_u = sum(r["upserted"] for r in results)
        total_m = sum(r["matched"] for r in results)
        logger.info(f"전체 완료: {len(accounts)}개 계정, 조회 {total_f}건, 저장 {total_u}건, 매칭 {total_m}건")

        return results


def main():
    parser = argparse.ArgumentParser(description="발주서(주문) 동기화")
    parser.add_argument("--days", type=int, default=7, help="동기화 기간 (일, 기본 7)")
    parser.add_argument("--account", type=str, default=None, help="특정 계정명 (기본: 전체)")
    parser.add_argument("--status", type=str, default=None,
                        help="특정 상태만 (ACCEPT/INSTRUCT/DEPARTURE/DELIVERING/FINAL_DELIVERY/NONE_TRACKING)")
    args = parser.parse_args()

    statuses = [args.status] if args.status else None

    syncer = OrderSync()
    results = syncer.sync_all(days=args.days, account_name=args.account, statuses=statuses)

    # 리포트
    print("\n" + "=" * 60)
    print("주문 동기화 결과")
    print("=" * 60)
    for r in results:
        print(f"  {r['account']:12s} | 조회 {r['fetched']:5d} | 저장 {r['upserted']:5d} | 매칭 {r['matched']:5d}")
    print("=" * 60)

    # DB 확인
    eng = get_engine_for_db()
    with eng.connect() as conn:
        cnt = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()
        print(f"\norders 총 레코드: {cnt:,}건")


if __name__ == "__main__":
    main()
