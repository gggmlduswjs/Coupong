"""
반품/취소 동기화 스크립트
============================
WING Return Request API → return_requests 테이블

사용법:
    python scripts/sync_returns.py              # 기본 30일
    python scripts/sync_returns.py --days 60    # 최근 60일
    python scripts/sync_returns.py --account 007-book  # 특정 계정만
    python scripts/sync_returns.py --status RU         # 특정 상태만
"""
import os
import sys
import json
import argparse
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional, Callable

from sqlalchemy import create_engine, text

# 프로젝트 루트
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
from app.services.wing_sync_base import get_accounts, create_wing_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 조회 대상 상태 목록
# RU: 출고중지요청, UC: 반품접수(미확인), CC: 쿠팡확인요청, PR: 반품처리완료
RETURN_STATUSES = ["RU", "UC", "CC", "PR"]


class ReturnSync:
    """반품/취소 동기화 엔진"""

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS return_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        receipt_id BIGINT NOT NULL,
        order_id BIGINT,
        payment_id BIGINT,
        receipt_type VARCHAR(10),
        receipt_status VARCHAR(40),
        created_at_api DATETIME,
        modified_at_api DATETIME,
        requester_name VARCHAR(100),
        requester_phone VARCHAR(50),
        requester_address VARCHAR(500),
        requester_address_detail VARCHAR(200),
        requester_zip_code VARCHAR(10),
        cancel_reason_category1 VARCHAR(100),
        cancel_reason_category2 VARCHAR(100),
        cancel_reason TEXT,
        cancel_count_sum INTEGER,
        return_delivery_id BIGINT,
        return_delivery_type VARCHAR(20),
        release_stop_status VARCHAR(30),
        fault_by_type VARCHAR(20),
        pre_refund BOOLEAN,
        complete_confirm_type VARCHAR(30),
        complete_confirm_date DATETIME,
        reason_code VARCHAR(50),
        reason_code_text VARCHAR(200),
        return_shipping_charge INTEGER,
        enclose_price INTEGER,
        return_items_json TEXT,
        return_delivery_json TEXT,
        raw_json TEXT,
        listing_id INTEGER REFERENCES listings(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(account_id, receipt_id)
    )
    """

    CREATE_INDEXES_SQL = [
        "CREATE INDEX IF NOT EXISTS ix_return_account_created ON return_requests(account_id, created_at_api)",
        "CREATE INDEX IF NOT EXISTS ix_return_account_status ON return_requests(account_id, receipt_status)",
        "CREATE INDEX IF NOT EXISTS ix_return_order_id ON return_requests(order_id)",
    ]

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(ROOT / "coupang_auto.db")
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 30})
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
        self._ensure_table()

    def _ensure_table(self):
        """테이블이 없으면 생성"""
        with self.engine.connect() as conn:
            conn.execute(text(self.CREATE_TABLE_SQL))
            for idx_sql in self.CREATE_INDEXES_SQL:
                conn.execute(text(idx_sql))
            conn.commit()
        logger.info("return_requests 테이블 확인 완료")

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
        return str(dt_str)[:19]

    def _match_listing(self, conn, account_id: int, seller_product_id, product_name: str = None) -> Optional[int]:
        """seller_product_id 또는 product_name으로 listings 매칭"""
        if seller_product_id:
            row = conn.execute(text(
                "SELECT id FROM listings WHERE account_id = :aid AND coupang_product_id = :pid LIMIT 1"
            ), {"aid": account_id, "pid": str(seller_product_id)}).fetchone()
            if row:
                return row[0]
        if product_name:
            row = conn.execute(text(
                "SELECT id FROM listings WHERE account_id = :aid AND product_name = :name LIMIT 1"
            ), {"aid": account_id, "name": product_name}).fetchone()
            if row:
                return row[0]
        return None

    def _extract_shipping_charge(self, data: dict) -> Optional[int]:
        """반품배송비 추출 (returnShippingCharge.units)"""
        charge = data.get("returnShippingCharge")
        if isinstance(charge, dict):
            return int(charge.get("units", 0))
        if isinstance(charge, (int, float)):
            return int(charge)
        return None

    def _extract_enclose_price(self, data: dict) -> Optional[int]:
        """동봉배송비 추출 (enclosePrice.units)"""
        price = data.get("enclosePrice")
        if isinstance(price, dict):
            return int(price.get("units", 0))
        if isinstance(price, (int, float)):
            return int(price)
        return None

    def sync_account(self, account: dict, date_from: date, date_to: date,
                     statuses: List[str] = None,
                     progress_callback: Callable = None) -> dict:
        """
        계정 1개의 반품/취소 동기화

        Returns:
            {"account": str, "fetched": int, "upserted": int, "matched": int}
        """
        account_id = account["id"]
        account_name = account["account_name"]
        client = self._create_client(account)

        if statuses is None:
            statuses = RETURN_STATUSES

        logger.info(f"[{account_name}] 반품 동기화 시작: {date_from} ~ {date_to}")

        # 날짜 범위를 31일 윈도우로 분할
        windows = self._split_date_range(date_from, date_to)
        total_fetched = 0
        total_upserted = 0
        total_matched = 0

        for wi, (w_from, w_to) in enumerate(windows):
            # 상태별 반품 조회 → receipt_id 기준 중복 제거
            seen_ids = set()
            all_returns = []

            for status in statuses:
                logger.info(f"  [{account_name}] 윈도우 {wi+1}/{len(windows)} 상태={status}: {w_from} ~ {w_to}")
                try:
                    items = client.get_all_return_requests(w_from, w_to, status=status)
                    for item in items:
                        rid = item.get("receiptId")
                        if rid and rid not in seen_ids:
                            seen_ids.add(rid)
                            all_returns.append(item)
                except CoupangWingError as e:
                    logger.error(f"  [{account_name}] API 오류 (반품 {status}): {e}")

            # 취소 유형도 별도 조회
            logger.info(f"  [{account_name}] 윈도우 {wi+1}/{len(windows)} cancelType=CANCEL: {w_from} ~ {w_to}")
            try:
                cancel_returns = client.get_all_return_requests(w_from, w_to, cancel_type="CANCEL")
                for cr in cancel_returns:
                    rid = cr.get("receiptId")
                    if rid and rid not in seen_ids:
                        seen_ids.add(rid)
                        all_returns.append(cr)
            except CoupangWingError as e:
                logger.error(f"  [{account_name}] API 오류 (취소): {e}")

            for ret_data in all_returns:
                total_fetched += 1
                receipt_id = ret_data.get("receiptId")
                if not receipt_id:
                    continue

                # returnItems에서 상품 정보 추출
                return_items = ret_data.get("returnItems", [])
                seller_product_id = None
                product_name = None
                if return_items:
                    first_item = return_items[0]
                    seller_product_id = first_item.get("sellerProductId")
                    product_name = first_item.get("sellerProductName", "")

                # 수량 합산
                cancel_count_sum = sum(
                    int(item.get("cancelCount", 0) or 0)
                    for item in return_items
                ) if return_items else int(ret_data.get("cancelCountSum", 0) or 0)

                params = {
                    "account_id": account_id,
                    "receipt_id": int(receipt_id),
                    "order_id": int(ret_data.get("orderId", 0) or 0) or None,
                    "payment_id": int(ret_data.get("paymentId", 0) or 0) or None,
                    "receipt_type": ret_data.get("receiptType", ""),
                    "receipt_status": ret_data.get("receiptStatus", ""),
                    "created_at_api": self._parse_datetime(ret_data.get("createdAt")),
                    "modified_at_api": self._parse_datetime(ret_data.get("modifiedAt")),
                    "requester_name": ret_data.get("requesterName", ""),
                    "requester_phone": ret_data.get("requesterPhone", ""),
                    "requester_address": ret_data.get("requesterAddress", ""),
                    "requester_address_detail": ret_data.get("requesterAddressDetail", ""),
                    "requester_zip_code": ret_data.get("requesterZipCode", ""),
                    "cancel_reason_category1": ret_data.get("cancelReasonCategory1", ""),
                    "cancel_reason_category2": ret_data.get("cancelReasonCategory2", ""),
                    "cancel_reason": ret_data.get("cancelReason", ""),
                    "cancel_count_sum": cancel_count_sum,
                    "return_delivery_id": int(ret_data.get("returnDeliveryId", 0) or 0) or None,
                    "return_delivery_type": ret_data.get("returnDeliveryType", ""),
                    "release_stop_status": ret_data.get("releaseStopStatus", ""),
                    "fault_by_type": ret_data.get("faultByType", ""),
                    "pre_refund": bool(ret_data.get("preRefund", False)),
                    "complete_confirm_type": ret_data.get("completeConfirmType", ""),
                    "complete_confirm_date": self._parse_datetime(ret_data.get("completeConfirmDate")),
                    "reason_code": ret_data.get("reasonCode", ""),
                    "reason_code_text": ret_data.get("reasonCodeText", ""),
                    "return_shipping_charge": self._extract_shipping_charge(ret_data),
                    "enclose_price": self._extract_enclose_price(ret_data),
                    "return_items_json": json.dumps(return_items, ensure_ascii=False, default=str)[:5000] if return_items else None,
                    "return_delivery_json": json.dumps(ret_data.get("returnDeliveryDtos", []), ensure_ascii=False, default=str)[:5000] if ret_data.get("returnDeliveryDtos") else None,
                    "raw_json": json.dumps(ret_data, ensure_ascii=False, default=str)[:5000],
                    "listing_id": None,
                    "updated_at": datetime.utcnow().isoformat(),
                }

                # 건별 커밋 + 재시도 (DB 잠금 방지)
                for attempt in range(3):
                    try:
                        with self.engine.connect() as conn:
                            # listing 매칭
                            listing_id = self._match_listing(conn, account_id, seller_product_id, product_name)
                            if listing_id:
                                params["listing_id"] = listing_id
                                total_matched += 1

                            conn.execute(text("""
                                INSERT OR REPLACE INTO return_requests
                                (account_id, receipt_id, order_id, payment_id,
                                 receipt_type, receipt_status,
                                 created_at_api, modified_at_api,
                                 requester_name, requester_phone, requester_address,
                                 requester_address_detail, requester_zip_code,
                                 cancel_reason_category1, cancel_reason_category2, cancel_reason,
                                 cancel_count_sum,
                                 return_delivery_id, return_delivery_type, release_stop_status,
                                 fault_by_type, pre_refund,
                                 complete_confirm_type, complete_confirm_date,
                                 reason_code, reason_code_text,
                                 return_shipping_charge, enclose_price,
                                 return_items_json, return_delivery_json, raw_json,
                                 listing_id, updated_at)
                                VALUES
                                (:account_id, :receipt_id, :order_id, :payment_id,
                                 :receipt_type, :receipt_status,
                                 :created_at_api, :modified_at_api,
                                 :requester_name, :requester_phone, :requester_address,
                                 :requester_address_detail, :requester_zip_code,
                                 :cancel_reason_category1, :cancel_reason_category2, :cancel_reason,
                                 :cancel_count_sum,
                                 :return_delivery_id, :return_delivery_type, :release_stop_status,
                                 :fault_by_type, :pre_refund,
                                 :complete_confirm_type, :complete_confirm_date,
                                 :reason_code, :reason_code_text,
                                 :return_shipping_charge, :enclose_price,
                                 :return_items_json, :return_delivery_json, :raw_json,
                                 :listing_id, :updated_at)
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

    def sync_all(self, days: int = 30, account_name: str = None,
                 statuses: List[str] = None,
                 progress_callback: Callable = None) -> List[dict]:
        """
        전체 계정 반품/취소 동기화

        Args:
            days: 동기화 기간 (일, 기본 30)
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

        logger.info(f"반품 동기화: {len(accounts)}개 계정, {date_from} ~ {date_to}")

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
    parser = argparse.ArgumentParser(description="반품/취소 동기화")
    parser.add_argument("--days", type=int, default=30, help="동기화 기간 (일, 기본 30)")
    parser.add_argument("--account", type=str, default=None, help="특정 계정명 (기본: 전체)")
    parser.add_argument("--status", type=str, default=None,
                        help="특정 상태만 (RU/UC/CC/PR)")
    args = parser.parse_args()

    statuses = [args.status] if args.status else None

    syncer = ReturnSync()
    results = syncer.sync_all(days=args.days, account_name=args.account, statuses=statuses)

    # 리포트
    print("\n" + "=" * 60)
    print("반품/취소 동기화 결과")
    print("=" * 60)
    for r in results:
        print(f"  {r['account']:12s} | 조회 {r['fetched']:5d} | 저장 {r['upserted']:5d} | 매칭 {r['matched']:5d}")
    print("=" * 60)

    # DB 확인
    from sqlalchemy import create_engine as ce
    eng = ce(f"sqlite:///{ROOT / 'coupang_auto.db'}")
    with eng.connect() as conn:
        cnt = conn.execute(text("SELECT COUNT(*) FROM return_requests")).scalar()
        print(f"\nreturn_requests 총 레코드: {cnt:,}건")


if __name__ == "__main__":
    main()
