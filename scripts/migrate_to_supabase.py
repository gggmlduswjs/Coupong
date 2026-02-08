"""
로컬 SQLite → Supabase PostgreSQL 마이그레이션 (REST API 방식)
===============================================================
PostgREST API로 HTTPS를 통해 데이터 전송 (IPv6 불필요)

사용법:
    python scripts/migrate_to_supabase.py                           # 전체 마이그레이션
    python scripts/migrate_to_supabase.py --tables books,products   # 특정 테이블만
    python scripts/migrate_to_supabase.py --verify                  # 검증만
    python scripts/migrate_to_supabase.py --upsert --tables orders,listings  # 재실행 시 중복 스킵(UPSERT)

사전 준비:
    1. Supabase SQL Editor에서 scripts/supabase_schema.sql 실행
    2. .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY 설정
"""
import os
import sys
import argparse
import sqlite3
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from datetime import date, datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "coupang_auto.db"


def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                os.environ.setdefault(key.strip(), value.strip())


def supabase_request(method, table, data=None, params=None, prefer_upsert=False):
    """Supabase PostgREST API 호출. prefer_upsert=True 시 ON CONFLICT (id) DO NOTHING (재실행 시 중복 스킵)"""
    base_url = os.environ["SUPABASE_URL"]
    service_key = os.environ["SUPABASE_SERVICE_KEY"]

    params = dict(params) if params else {}
    if prefer_upsert and method == "POST" and data is not None:
        params["on_conflict"] = "id"

    url = f"{base_url}/rest/v1/{table}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())

    prefer = "return=minimal, resolution=ignore-duplicates" if prefer_upsert else "return=minimal"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }

    # orders 전송 직전 ID 컬럼을 숫자로 보정 (22003 방지)
    if method == "POST" and table == "orders" and data is not None:
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict):
                coerce_orders_bigint(item)
    body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8') if data else None
    req = Request(url, data=body, headers=headers, method=method)

    try:
        with urlopen(req, timeout=60) as resp:
            if resp.status in (200, 201, 204):
                content = resp.read().decode('utf-8')
                return {"ok": True, "data": json.loads(content) if content.strip() else None}
            return {"ok": True}
    except HTTPError as e:
        error_body = e.read().decode('utf-8')
        return {"ok": False, "status": e.code, "error": error_body[:500]}


def get_table_order():
    """FK 의존성 순서"""
    return [
        'accounts', 'publishers', 'tasks',
        'books', 'bundle_skus', 'ad_spends', 'settlement_history',
        'products',
        'listings',
        'sales', 'analysis_results', 'inventory_sync_log',
        'orders', 'return_requests', 'revenue_history', 'ad_performances',
    ]


# Supabase VARCHAR(20)/(10) 컬럼: 전송 시 이 길이로 자름 (22001 방지, ALTER 없이 통과)
SHORT_VARCHAR_MAX = {
    "listings": {"product_type": 20, "coupang_status": 20, "shipping_policy": 20, "display_category_code": 20, "delivery_charge_type": 20, "winner_status": 20, "upload_method": 20, "isbn": 100},
    "orders": {"shipment_type": 20, "receiver_post_code": 10},
    "return_requests": {"receipt_type": 20, "return_delivery_type": 20, "fault_by_type": 20, "requester_zip_code": 10},
    "revenue_history": {"sale_type": 20},
}
# listings: 위 목록 외 문자열도 20자로 자름 (Supabase VARCHAR(20) 누락 대비). 아래 컬럼은 자르지 않음.
LISTINGS_STRING_MAX = 20
LISTINGS_LONG_COLUMNS = {"product_name", "raw_json", "error_message", "bundle_key", "brand", "coupang_product_id", "vendor_item_id", "item_id"}
# 23503 (listing_id FK 없음) 시 listing_id=null 로 재시도할 테이블
LISTING_FK_TABLES = {"orders", "revenue_history"}
# orders: 21억 초과 ID → JSON에서 숫자로 보내야 함 (문자열이면 22003)
ORDERS_BIGINT_COLUMNS = {"shipment_box_id", "order_id", "vendor_item_id", "product_id", "seller_product_id"}


def serialize_row(row_dict):
    """SQLite 값 → JSON 직렬화"""
    result = {}
    for k, v in row_dict.items():
        if v is None:
            result[k] = None
        elif isinstance(v, (date, datetime)):
            result[k] = v.isoformat()
        elif isinstance(v, bytes):
            result[k] = v.decode('utf-8', errors='replace')
        else:
            result[k] = v
    return result


def _to_int_if_numeric(v):
    """문자열/float를 int로 (22003 방지). 변환 불가면 None."""
    if v is None or isinstance(v, int):
        return v
    if isinstance(v, float) and v == v and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            return int(s)
    return None


def coerce_orders_bigint(row_dict):
    """orders의 ID 컬럼을 int로 보내서 JSON이 숫자로 직렬화되게 함 (22003 방지)"""
    for col in ORDERS_BIGINT_COLUMNS:
        if col not in row_dict:
            continue
        v = row_dict[col]
        n = _to_int_if_numeric(v)
        if n is not None:
            row_dict[col] = n


def truncate_short_varchar(row_dict, table_name):
    """VARCHAR(20) 등 짧은 컬럼 값을 최대 길이로 자름 (22001 방지)"""
    limits = SHORT_VARCHAR_MAX.get(table_name, {})
    for col, max_len in limits.items():
        if col not in row_dict:
            continue
        v = row_dict[col]
        if isinstance(v, str) and len(v) > max_len:
            row_dict[col] = v[:max_len]
    # listings: 나머지 문자열 컬럼도 20자 초과 시 자름 (Supabase VARCHAR(20) 누락 대비)
    if table_name == "listings":
        for col, v in list(row_dict.items()):
            if col in LISTINGS_LONG_COLUMNS:
                continue
            if isinstance(v, str) and len(v) > LISTINGS_STRING_MAX:
                row_dict[col] = v[:LISTINGS_STRING_MAX]


def clear_table(table_name):
    """테이블 데이터 삭제 (재실행 가능하게)"""
    # PostgREST DELETE는 필터 필요
    result = supabase_request("DELETE", table_name, params={"id": "gt.0"})
    if not result["ok"]:
        # 필터 없이 전체 삭제 시도
        result = supabase_request("DELETE", table_name, params={"id": "gte.0"})
    return result


def migrate_table(sqlite_conn, table_name, batch_size=200, use_upsert=False):
    """단일 테이블 데이터 마이그레이션. use_upsert=True 시 기존 행은 스킵(ON CONFLICT DO NOTHING), 누락분만 INSERT"""
    cursor = sqlite_conn.cursor()

    # 행 수
    cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
    total = cursor.fetchone()[0]
    if total == 0:
        print(f"  {table_name}: 0행 (스킵)")
        return 0

    # 컬럼 정보
    cursor.execute(f"PRAGMA table_info([{table_name}])")
    columns = [row[1] for row in cursor.fetchall()]

    # upsert 모드가 아니면 기존 데이터 삭제 후 전체 INSERT
    if not use_upsert:
        clear_table(table_name)

    # 데이터 읽기 + 배치 INSERT (upsert 시 중복 id는 스킵)
    cursor.execute(f"SELECT * FROM [{table_name}]")

    inserted = 0
    batch = []
    errors = 0
    start = time.time()

    for row in cursor:
        row_dict = {}
        for i, col in enumerate(columns):
            row_dict[col] = row[i]
        serialized = serialize_row(row_dict)
        truncate_short_varchar(serialized, table_name)
        if table_name == "orders":
            coerce_orders_bigint(serialized)
        batch.append(serialized)

        if len(batch) >= batch_size:
            result = supabase_request("POST", table_name, data=batch, prefer_upsert=use_upsert)
            if result["ok"]:
                inserted += len(batch)
            else:
                errors += 1
                err_body = result.get("error", "")
                if errors <= 3:
                    print(f"    ⚠ 배치 에러: {err_body[:100]}")
                if "22001" in err_body or "value too long" in err_body.lower():
                    print("    → 22001 해결: Supabase SQL Editor에서 scripts/supabase_alter_varchar.sql 실행 후 재시도하세요.")
                if "22003" in err_body and "out of range" in err_body.lower():
                    print("    → 22003 해결: Supabase SQL Editor에서 scripts/supabase_alter_orders_bigint.sql 실행 후 재시도하세요.")
                    if table_name == "orders" and batch:
                        s = batch[0]
                        info = {c: f"{type(s.get(c)).__name__}={s.get(c)}" for c in ORDERS_BIGINT_COLUMNS if c in s}
                        print("    [22003 디버그] 첫 행 ID 컬럼 타입/값:", info)
                if "23503" in err_body and "listing_id" in err_body and "listings" in err_body:
                    print("    → 23503: listing_id 없는 행은 listing_id=null 로 재시도합니다.")
                # 1건씩 재시도 (23503 시 listing_id=null 로 재시도)
                for item in batch:
                    r = supabase_request("POST", table_name, data=[item], prefer_upsert=use_upsert)
                    if r["ok"]:
                        inserted += 1
                    elif table_name in LISTING_FK_TABLES and "23503" in r.get("error", "") and "listing_id" in r.get("error", ""):
                        item_fk_null = dict(item)
                        item_fk_null["listing_id"] = None
                        r2 = supabase_request("POST", table_name, data=[item_fk_null], prefer_upsert=use_upsert)
                        if r2["ok"]:
                            inserted += 1
            batch = []
            # 진행 표시
            if inserted % 1000 == 0 and inserted > 0:
                print(f"    → {inserted:,}/{total:,}...")

    # 나머지
    if batch:
        result = supabase_request("POST", table_name, data=batch, prefer_upsert=use_upsert)
        if result["ok"]:
            inserted += len(batch)
        else:
            err_body = result.get("error", "")
            if "22001" in err_body or "value too long" in err_body.lower():
                print("    → 22001 해결: Supabase SQL Editor에서 scripts/supabase_alter_varchar.sql 실행 후 재시도하세요.")
            if "22003" in err_body and "out of range" in err_body.lower():
                print("    → 22003 해결: Supabase SQL Editor에서 scripts/supabase_alter_orders_bigint.sql 실행 후 재시도하세요.")
            if "23503" in err_body and "listing_id" in err_body:
                print("    → 23503: listing_id 없는 행은 listing_id=null 로 재시도합니다.")
            for item in batch:
                r = supabase_request("POST", table_name, data=[item], prefer_upsert=use_upsert)
                if r["ok"]:
                    inserted += 1
                elif table_name in LISTING_FK_TABLES and "23503" in r.get("error", "") and "listing_id" in r.get("error", ""):
                    item_fk_null = dict(item)
                    item_fk_null["listing_id"] = None
                    r2 = supabase_request("POST", table_name, data=[item_fk_null], prefer_upsert=use_upsert)
                    if r2["ok"]:
                        inserted += 1

    elapsed = time.time() - start
    rate = inserted / elapsed if elapsed > 0 else 0
    status = "✓" if inserted == total else "⚠"
    mode_note = " [upsert: 중복 스킵]" if use_upsert else ""
    print(f"  {status} {table_name}: {inserted:,}/{total:,}행 ({elapsed:.1f}초, {rate:.0f}행/s){mode_note}")

    # 시퀀스 리셋 (별도 RPC 필요 없음 — Supabase가 자동 처리)
    return inserted


def verify(sqlite_conn):
    """검증: SQLite vs Supabase 행 수 비교"""
    print("\n[검증] SQLite vs Supabase 행 수 비교")
    cursor = sqlite_conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'")
    tables = sorted(row[0] for row in cursor.fetchall())

    all_ok = True
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
        sqlite_count = cursor.fetchone()[0]

        # Supabase 행 수 조회
        result = supabase_request("GET", table, params={
            "select": "id",
            "limit": "0",
        })
        # HEAD 요청으로 count 조회
        base_url = os.environ["SUPABASE_URL"]
        service_key = os.environ["SUPABASE_SERVICE_KEY"]
        url = f"{base_url}/rest/v1/{table}?select=count"
        headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Prefer": "count=exact",
        }
        req = Request(url, headers=headers, method="HEAD")
        try:
            with urlopen(req, timeout=15) as resp:
                content_range = resp.headers.get("Content-Range", "")
                # 형식: */123  또는 0-99/123
                pg_count = int(content_range.split("/")[-1]) if "/" in content_range else -1
        except Exception:
            pg_count = -1

        if pg_count >= 0:
            status = "✓" if sqlite_count == pg_count else "⚠"
            if sqlite_count != pg_count:
                all_ok = False
            print(f"  {status} {table}: SQLite={sqlite_count:,} → Supabase={pg_count:,}")
        else:
            print(f"  ? {table}: SQLite={sqlite_count:,} → Supabase=확인불가")
            all_ok = False

    return all_ok


def main():
    parser = argparse.ArgumentParser(description="SQLite → Supabase 마이그레이션 (REST API)")
    parser.add_argument("--tables", help="마이그레이션할 테이블 (쉼표 구분)")
    parser.add_argument("--verify", action="store_true", help="검증만 실행")
    parser.add_argument("--batch-size", type=int, default=200, help="배치 크기")
    parser.add_argument("--upsert", action="store_true", help="ON CONFLICT (id) DO NOTHING: 기존 행은 스킵, 누락분만 INSERT (재실행 시 23505 방지)")
    args = parser.parse_args()

    load_env()

    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

    if not supabase_url or not supabase_key:
        print("✗ .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY를 설정하세요.")
        sys.exit(1)

    # 연결 테스트
    print(f"Supabase: {supabase_url}")
    result = supabase_request("GET", "", params={"limit": "0"})

    # SQLite 연결
    sqlite_conn = sqlite3.connect(str(DB_PATH))

    if args.verify:
        ok = verify(sqlite_conn)
        sqlite_conn.close()
        sys.exit(0 if ok else 1)

    # 대상 테이블
    target_tables = set(args.tables.split(",")) if args.tables else None
    table_order = get_table_order()

    # SQLite 테이블 확인
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'")
    sqlite_tables = {row[0] for row in cursor.fetchall()}

    tables_to_migrate = [t for t in table_order if t in sqlite_tables]
    if target_tables:
        tables_to_migrate = [t for t in tables_to_migrate if t in target_tables]

    print(f"\n마이그레이션 대상: {len(tables_to_migrate)}개 테이블" + (" [UPSERT 모드: 기존 id 스킵]" if args.upsert else ""))

    total_rows = 0
    start = time.time()

    for table in tables_to_migrate:
        rows = migrate_table(sqlite_conn, table, args.batch_size, use_upsert=args.upsert)
        total_rows += rows

    elapsed = time.time() - start
    print(f"\n✓ 총 {total_rows:,}행 마이그레이션 완료 ({elapsed:.1f}초)")

    # 검증
    verify(sqlite_conn)

    sqlite_conn.close()

    # Streamlit secrets 안내
    print(f"\n{'=' * 60}")
    print("Streamlit Cloud Secrets:")
    print(f"{'=' * 60}")
    print("[supabase]")
    print(f'url = "{supabase_url}"')
    print(f'key = "{supabase_key}"')


if __name__ == "__main__":
    main()
