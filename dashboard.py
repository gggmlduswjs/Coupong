"""
쿠팡 도서 자동화 대시보드
=========================
계정별 상품 관리 + API 등록 기능
실행: streamlit run dashboard.py
"""
import os
import sys
import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from pathlib import Path
from datetime import datetime
import logging

# 프로젝트 루트를 path에 추가
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
from uploaders.coupang_api_uploader import CoupangAPIUploader, _build_book_notices, _build_book_attributes
from app.constants import WING_ACCOUNT_ENV_MAP, BOOK_CATEGORY_MAP, BOOK_DISCOUNT_RATE, COUPANG_FEE_RATE, DEFAULT_SHIPPING_COST, FREE_SHIPPING_THRESHOLD

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# ─── DB ───
DB_PATH = ROOT / "coupang_auto.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 30})

# SQLite WAL 모드 + busy_timeout (동시 접근 허용)
from sqlalchemy import event as _sa_event
@_sa_event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA busy_timeout=30000")
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    cursor.close()

# ─── 페이지 설정 ───
st.set_page_config(page_title="쿠팡 도서 자동화", page_icon="📚", layout="wide")


# ─── 유틸 ───
@st.cache_data(ttl=10)
def query_df(sql: str, params: dict = None) -> pd.DataFrame:
    try:
        if params:
            return pd.read_sql(text(sql), engine, params=params)
        return pd.read_sql(sql, engine)
    except Exception as e:
        st.error(f"DB 오류: {e}")
        return pd.DataFrame()


_MONEY_KEYWORDS = ["판매", "마진", "정산", "수수료", "지급", "차감", "유보", "환불금액"]

def fmt_money_df(df: pd.DataFrame) -> pd.DataFrame:
    """금액 컬럼에 천단위 쉼표 포맷 적용"""
    d = df.copy()
    for col in d.columns:
        if any(kw in col for kw in _MONEY_KEYWORDS) and pd.api.types.is_numeric_dtype(d[col]):
            d[col] = d[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")
    return d


def run_sql(sql: str, params: dict = None):
    """INSERT/UPDATE/DELETE 실행용"""
    with engine.connect() as conn:
        conn.execute(text(sql), params or {})
        conn.commit()


def create_wing_client(account_row):
    account_name = account_row["account_name"]
    env_prefix = WING_ACCOUNT_ENV_MAP.get(account_name, "")
    vendor_id = account_row.get("vendor_id") or ""
    access_key = account_row.get("wing_access_key") or ""
    secret_key = account_row.get("wing_secret_key") or ""
    if not access_key and env_prefix:
        vendor_id = os.getenv(f"{env_prefix}_VENDOR_ID", vendor_id)
        access_key = os.getenv(f"{env_prefix}_ACCESS_KEY", "")
        secret_key = os.getenv(f"{env_prefix}_SECRET_KEY", "")
    if not all([vendor_id, access_key, secret_key]):
        return None
    return CoupangWingClient(vendor_id, access_key, secret_key)


def product_to_upload_data(row):
    return {
        "product_name": row.get("title", ""),
        "publisher": row.get("publisher_name", ""),
        "author": row.get("author", ""),
        "isbn": row.get("isbn", ""),
        "original_price": int(row.get("list_price", 0)),
        "sale_price": int(row.get("sale_price", 0)),
        "main_image_url": row.get("image_url", "") or "",
        "description": row.get("description", "") or "",
        "shipping_policy": row.get("shipping_policy", "free"),
    }


# ─── 사이드바 ───
st.sidebar.title("📚 쿠팡 도서 자동화")

accounts_df = query_df("""
    SELECT id, account_name, vendor_id, wing_api_enabled,
           wing_access_key, wing_secret_key,
           outbound_shipping_code, return_center_code
    FROM accounts WHERE is_active = 1 ORDER BY account_name
""")
account_names = accounts_df["account_name"].tolist() if not accounts_df.empty else []

selected_account_name = st.sidebar.selectbox("계정 선택", account_names, index=0 if account_names else None)

selected_account = None
if selected_account_name and not accounts_df.empty:
    mask = accounts_df["account_name"] == selected_account_name
    if mask.any():
        selected_account = accounts_df[mask].iloc[0]

st.sidebar.divider()
page = st.sidebar.radio("메뉴", ["매출", "트렌드", "정산", "광고", "주문", "상품 관리", "신규 등록", "수동 등록"])

if selected_account is not None:
    st.sidebar.divider()
    st.sidebar.caption("계정 정보")
    st.sidebar.text(f"Vendor: {selected_account.get('vendor_id', '-')}")
    st.sidebar.text(f"출고지: {selected_account.get('outbound_shipping_code', '-')}")
    st.sidebar.text(f"반품지: {selected_account.get('return_center_code', '-')}")


# ═══════════════════════════════════════
# 등록 현황
# ═══════════════════════════════════════
if page == "상품 관리":
    st.title("상품 관리")

    # ── 전체 요약 KPI ──
    _all_active = int(query_df("SELECT COUNT(*) as c FROM listings WHERE coupang_status = 'active'").iloc[0]['c'])
    _all_other = int(query_df("SELECT COUNT(*) as c FROM listings WHERE coupang_status != 'active'").iloc[0]['c'])
    _pub_cnt = int(query_df("SELECT COUNT(*) as c FROM publishers WHERE is_active = 1").iloc[0]['c'])
    _total_sale = int(query_df("SELECT COALESCE(SUM(sale_price), 0) as s FROM listings WHERE coupang_status = 'active'").iloc[0]['s'])
    _price_diff_cnt = int(query_df("""
        SELECT COUNT(*) as c FROM listings
        WHERE coupang_status = 'active' AND coupang_sale_price > 0 AND sale_price > 0 AND sale_price != coupang_sale_price
    """).iloc[0]['c'])
    _low_stock_cnt = int(query_df("""
        SELECT COUNT(*) as c FROM listings
        WHERE coupang_status = 'active' AND stock_quantity <= 3
    """).iloc[0]['c'])

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("판매중", f"{_all_active:,}개")
    c2.metric("기타", f"{_all_other:,}개")
    c3.metric("출판사", f"{_pub_cnt}개")
    c4.metric("총 판매가", f"₩{_total_sale:,}")
    c5.metric("가격 불일치", f"{_price_diff_cnt}건", delta=f"{_price_diff_cnt}" if _price_diff_cnt > 0 else None, delta_color="inverse")
    c6.metric("재고 부족", f"{_low_stock_cnt}건", delta=f"{_low_stock_cnt}" if _low_stock_cnt > 0 else None, delta_color="inverse")

    # ── WING 등록현황 KPI (API 키 있는 계정만) ──
    _wing_client = create_wing_client(selected_account) if selected_account is not None else None
    if _wing_client is not None:
        try:
            @st.cache_data(ttl=60)
            def _fetch_inflow_status(_vendor_id):
                _c = create_wing_client(selected_account)
                if _c is None:
                    return None
                return _c.get_inflow_status()

            _inflow = _fetch_inflow_status(selected_account.get("vendor_id", ""))
            if _inflow and isinstance(_inflow, dict):
                _inflow_data = _inflow.get("data", _inflow)
                _registered = _inflow_data.get("registeredCount", "-")
                _permitted = _inflow_data.get("permittedCount", "-")
                _restricted = _inflow_data.get("restricted", False)
                _iw1, _iw2, _iw3 = st.columns(3)
                _iw1.metric("WING 등록 상품", f"{_registered:,}건" if isinstance(_registered, int) else f"{_registered}건")
                _iw2.metric("등록 한도", f"{_permitted:,}건" if isinstance(_permitted, int) and _permitted < 2_000_000_000 else "무제한")
                _iw3.metric("판매 제한", "제한됨" if _restricted else "정상")
        except CoupangWingError as e:
            st.caption(f"WING 등록현황 조회 실패: {e.message}")
        except Exception:
            pass

    # ── 계정별 요약 테이블 ──
    acct_sum = query_df("""
        SELECT a.account_name as 계정,
               COUNT(l.id) as 전체,
               SUM(CASE WHEN l.coupang_status = 'active' THEN 1 ELSE 0 END) as 판매중,
               SUM(CASE WHEN l.coupang_status != 'active' THEN 1 ELSE 0 END) as 기타
        FROM accounts a
        LEFT JOIN listings l ON a.id = l.account_id
        WHERE a.is_active = 1
        GROUP BY a.id ORDER BY a.account_name
    """)
    if not acct_sum.empty:
        st.dataframe(acct_sum, width="stretch", hide_index=True)

    with st.expander("출판사별 도서 수"):
        pub_df = query_df("""
            SELECT p.name as 출판사, p.margin_rate as '매입율(%)',
                   COUNT(b.id) as 도서수,
                   COALESCE(ROUND(AVG(pr.net_margin)), 0) as '평균마진(원)'
            FROM publishers p
            LEFT JOIN books b ON p.id = b.publisher_id
            LEFT JOIN products pr ON b.id = pr.book_id
            WHERE p.is_active = 1 GROUP BY p.id HAVING 도서수 > 0
            ORDER BY 도서수 DESC LIMIT 10
        """)
        if not pub_df.empty:
            st.dataframe(fmt_money_df(pub_df), width="stretch", hide_index=True)

    st.divider()

    # ── 계정 필요 ──
    if selected_account is None:
        st.info("왼쪽에서 계정을 선택하면 상세 조회할 수 있습니다.")
        st.stop()

    account_id = int(selected_account["id"])

    # ═══ 4개 탭 ═══
    pm_tab1, pm_tab2, pm_tab3, pm_tab4 = st.tabs(["📦 상품 목록", "💰 가격/재고", "📋 등록 현황", "📜 상태 이력"])

    # ─────────────────────────────────────────────
    # Tab 1: 상품 목록
    # ─────────────────────────────────────────────
    with pm_tab1:
        st.subheader(f"{selected_account_name} 상품 목록")

        _status_counts = query_df("SELECT coupang_status, COUNT(*) as cnt FROM listings WHERE account_id = :acct_id GROUP BY coupang_status", {"acct_id": account_id})
        _sc = dict(zip(_status_counts["coupang_status"], _status_counts["cnt"])) if not _status_counts.empty else {}
        _k1, _k2, _k3, _k4 = st.columns(4)
        _k1.metric("판매중", f"{_sc.get('active', 0):,}건")
        _k2.metric("대기", f"{_sc.get('pending', 0):,}건")
        _k3.metric("품절/중지", f"{_sc.get('sold_out', 0) + _sc.get('stopped', 0):,}건")
        _k4.metric("전체", f"{sum(_sc.values()):,}건")

        col_f1, col_f2 = st.columns([1, 2])
        with col_f1:
            status_filter = st.selectbox("상태 필터", ["active", "전체", "pending", "rejected", "sold_out"], key="lst_st")
        with col_f2:
            search_q = st.text_input("검색 (상품명 / ISBN / SKU)", key="lst_search")

        where_parts = ["l.account_id = :acct_id"]
        _lst_params = {"acct_id": account_id}
        if status_filter != "전체":
            where_parts.append("l.coupang_status = :status")
            _lst_params["status"] = status_filter
        if search_q:
            where_parts.append("(l.product_name LIKE :sq OR l.isbn LIKE :sq OR l.coupang_product_id LIKE :sq)")
            _lst_params["sq"] = f"%{search_q}%"
        where_sql = " AND ".join(where_parts)

        listings_df = query_df(f"""
            SELECT COALESCE(l.product_name, '(미등록)') as 상품명,
                   COALESCE(l.original_price, 0) as 정가,
                   l.sale_price as 판매가,
                   l.delivery_charge_type as 배송유형,
                   COALESCE(l.delivery_charge, 0) as 배송비,
                   COALESCE(l.stock_quantity, 10) as 재고,
                   l.coupang_status as 상태,
                   l.isbn as ISBN,
                   COALESCE(l.brand, '') as 출판사,
                   COALESCE(l.coupang_product_id, '-') as 쿠팡ID,
                   COALESCE(l.vendor_item_id, '') as VID,
                   l.uploaded_at as 등록일
            FROM listings l
            WHERE {where_sql}
            ORDER BY l.uploaded_at DESC
        """, _lst_params)

        if not listings_df.empty:
            _cap_col, _dl_col = st.columns([4, 1])
            _cap_col.caption(f"총 {len(listings_df):,}건  |  행 클릭 → 하단 상세보기")
            _csv_lst = listings_df.to_csv(index=False).encode("utf-8-sig")
            _dl_col.download_button("📥 CSV", _csv_lst, f"products_{selected_account_name}.csv", "text/csv", key="dl_lst")

            gb = GridOptionsBuilder.from_dataframe(listings_df)
            gb.configure_selection(selection_mode="single", use_checkbox=False)
            gb.configure_grid_options(domLayout="normal")
            grid_resp = AgGrid(
                listings_df,
                gridOptions=gb.build(),
                update_on=["selectionChanged"],
                height=400,
                theme="streamlit",
            )

            selected = grid_resp["selected_rows"]
            if selected is not None and len(selected) > 0:
                sel = selected.iloc[0] if hasattr(selected, "iloc") else pd.Series(selected[0])

                st.divider()
                # 도서 정보 조회
                img_url, author, description = "", "", ""
                book_match = pd.DataFrame()
                if sel["ISBN"]:
                    book_match = query_df("SELECT image_url, author, description FROM books WHERE isbn = :isbn LIMIT 1", {"isbn": sel["ISBN"]})
                if book_match.empty:
                    _sel_name = sel["상품명"] or ""
                    if _sel_name:
                        book_match = query_df("SELECT image_url, author, description FROM books WHERE title = :title LIMIT 1", {"title": _sel_name})
                if not book_match.empty:
                    img_url = book_match.iloc[0]["image_url"] or ""
                    author = book_match.iloc[0]["author"] or ""
                    description = book_match.iloc[0]["description"] or ""

                # 상세 카드
                pc1, pc2 = st.columns([1, 3])
                with pc1:
                    if img_url:
                        try:
                            st.image(img_url, width=180)
                        except Exception:
                            st.markdown('<div style="width:180px;height:240px;background:#f0f0f0;display:flex;align-items:center;justify-content:center;border-radius:8px;color:#999;font-size:48px;">📖</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="width:180px;height:240px;background:#f0f0f0;display:flex;align-items:center;justify-content:center;border-radius:8px;color:#999;font-size:48px;">📖</div>', unsafe_allow_html=True)
                with pc2:
                    st.markdown(f"### {sel['상품명']}")
                    if author:
                        st.caption(f"저자: {author}")
                    dc1, dc2, dc3, dc4 = st.columns(4)
                    dc1.metric("정가", f"{int(sel['정가'] or 0):,}원")
                    dc2.metric("판매가", f"{int(sel['판매가'] or 0):,}원")
                    dc3.metric("상태", sel["상태"])
                    dc4.metric("쿠팡ID", sel["쿠팡ID"] or "-")
                    st.markdown(f"**ISBN:** `{sel['ISBN'] or '-'}`  |  **VID:** `{sel['VID'] or '-'}`  |  **등록일:** {sel['등록일'] or '-'}")
                    if description:
                        with st.expander("상품 설명"):
                            st.markdown(description[:500])

                # ── 실시간 조회 (WING API) ──
                _sel_vid = sel["VID"] or ""
                if _sel_vid and _wing_client:
                    with st.expander("실시간 정보 (WING API)"):
                        if st.button("실시간 조회", key="btn_realtime"):
                            try:
                                _inv_info = _wing_client.get_item_inventory(int(_sel_vid))
                                _inv_data = _inv_info.get("data", _inv_info)
                                _ri1, _ri2, _ri3, _ri4 = st.columns(4)
                                _ri1.metric("쿠팡 판매가", f"{_inv_data.get('salePrice', '-'):,}원" if isinstance(_inv_data.get('salePrice'), int) else str(_inv_data.get('salePrice', '-')))
                                _ri2.metric("기준가", f"{_inv_data.get('originalPrice', '-'):,}원" if isinstance(_inv_data.get('originalPrice'), int) else str(_inv_data.get('originalPrice', '-')))
                                _ri3.metric("재고", str(_inv_data.get('quantity', _inv_data.get('maximumBuyCount', '-'))))
                                _ri4.metric("판매상태", str(_inv_data.get('salesStatus', _inv_data.get('status', '-'))))
                                st.json(_inv_data)
                            except CoupangWingError as e:
                                st.error(f"API 오류: {e.message}")
                            except Exception as e:
                                st.error(f"조회 실패: {e}")

                # ── 판매 중지/재개 ──
                if _sel_vid and _wing_client:
                    with st.expander("판매 중지/재개"):
                        _sale_confirm = st.checkbox("작업을 확인합니다", key="sale_confirm")
                        _sc1, _sc2 = st.columns(2)
                        with _sc1:
                            if st.button("판매 중지", type="secondary", disabled=not _sale_confirm, key="btn_stop_sale"):
                                try:
                                    _wing_client.stop_item_sale(int(_sel_vid))
                                    run_sql("UPDATE listings SET coupang_status='sold_out' WHERE account_id=:aid AND vendor_item_id=:vid",
                                            {"aid": account_id, "vid": _sel_vid})
                                    st.success("판매 중지 완료")
                                    st.cache_data.clear()
                                    st.rerun()
                                except CoupangWingError as e:
                                    st.error(f"API 오류: {e.message}")
                        with _sc2:
                            if st.button("판매 재개", type="primary", disabled=not _sale_confirm, key="btn_resume_sale"):
                                try:
                                    _wing_client.resume_item_sale(int(_sel_vid))
                                    run_sql("UPDATE listings SET coupang_status='active' WHERE account_id=:aid AND vendor_item_id=:vid",
                                            {"aid": account_id, "vid": _sel_vid})
                                    st.success("판매 재개 완료")
                                    st.cache_data.clear()
                                    st.rerun()
                                except CoupangWingError as e:
                                    st.error(f"API 오류: {e.message}")

                # ── 수정 폼 ──
                with st.expander("수정"):
                    sel_title = sel["상품명"] or ""
                    lid_row = query_df("""
                        SELECT l.id, l.original_price FROM listings l
                        WHERE l.account_id = :acct_id
                          AND COALESCE(l.product_name, '') = :title
                          AND COALESCE(l.isbn, '') = :isbn
                        LIMIT 1
                    """, {"acct_id": account_id, "title": sel_title, "isbn": sel["ISBN"] or ""})
                    if not lid_row.empty:
                        lid = int(lid_row.iloc[0]["id"])
                        _cur_orig_price = int(lid_row.iloc[0]["original_price"] or 0)
                        with st.form("lst_edit_form"):
                            new_name = st.text_input("상품명", value=sel["상품명"] or "")
                            le1, le2, le3 = st.columns(3)
                            with le1:
                                new_sp = st.number_input("판매가", value=int(sel["판매가"] or 0), step=100)
                            with le2:
                                new_orig = st.number_input("기준가격(정가)", value=_cur_orig_price, step=100)
                            with le3:
                                status_opts = ["active", "pending", "rejected", "sold_out"]
                                cur_idx = status_opts.index(sel["상태"]) if sel["상태"] in status_opts else 0
                                new_status = st.selectbox("상태", status_opts, index=cur_idx)
                            if st.form_submit_button("저장", type="primary"):
                                try:
                                    run_sql("UPDATE listings SET product_name=:name, sale_price=:sp, original_price=:op, coupang_status=:st WHERE id=:id",
                                            {"name": new_name, "sp": new_sp, "op": new_orig, "st": new_status, "id": lid})
                                    # WING API 기준가격 변경
                                    if new_orig != _cur_orig_price and _sel_vid and _wing_client and new_orig > 0:
                                        try:
                                            _wing_client.update_original_price(int(_sel_vid), new_orig)
                                        except CoupangWingError as e:
                                            st.warning(f"기준가격 API 반영 실패: {e.message}")
                                    st.success("저장 완료")
                                    st.cache_data.clear()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"저장 실패: {e}")
        else:
            st.info("조건에 맞는 상품이 없습니다.")

    # ─────────────────────────────────────────────
    # Tab 2: 가격/재고 관리
    # ─────────────────────────────────────────────
    with pm_tab2:
        st.subheader("가격/재고 관리")

        # ── 일괄 동기화 (기존 기능) ──
        _sync_col1, _sync_col2, _sync_col3 = st.columns([2, 1, 3])
        with _sync_col1:
            _inv_acct = st.selectbox("동기화 계정", ["전체"] + account_names, key="inv_acct")
        with _sync_col2:
            _inv_dry = st.checkbox("Dry Run", value=True, key="inv_dry", help="실제 변경 없이 확인만")
        with _sync_col3:
            st.markdown("<br>", unsafe_allow_html=True)
            _btn_inv_sync = st.button("가격/재고 동기화", type="primary", key="btn_inv_sync", width="stretch")

        if _btn_inv_sync:
            try:
                from scripts.sync_inventory import InventorySync
                syncer = InventorySync(db_path=str(DB_PATH))
                _inv_acct_arg = None if _inv_acct == "전체" else _inv_acct
                _inv_progress = st.progress(0, text="가격/재고 동기화 중...")
                _inv_results = syncer.sync_all(
                    account_name=_inv_acct_arg,
                    dry_run=_inv_dry,
                    progress_callback=lambda cur, tot, msg: _inv_progress.progress(
                        min(cur / max(tot, 1), 1.0), text=msg),
                )
                _inv_progress.progress(1.0, text="완료!")
                _inv_total_price = sum(r["price_updated"] for r in _inv_results)
                _inv_total_stock = sum(r["stock_refilled"] for r in _inv_results)
                _inv_total_vid = sum(r["vendor_id_backfilled"] for r in _inv_results)
                _inv_total_err = sum(r["errors"] for r in _inv_results)
                _mode = "[DRY-RUN] " if _inv_dry else ""
                st.success(
                    f"{_mode}동기화 완료: {len(_inv_results)}개 계정 | "
                    f"가격변경 {_inv_total_price}건, 재고리필 {_inv_total_stock}건, "
                    f"VID백필 {_inv_total_vid}건, 오류 {_inv_total_err}건"
                )
                query_df.clear()
            except Exception as e:
                st.error(f"동기화 오류: {e}")
                logger.exception("가격/재고 동기화 오류")

        st.divider()

        # ── 가격 불일치 목록 ──
        st.markdown("#### 가격 불일치")
        _price_diff_df = query_df("""
            SELECT l.id, COALESCE(l.product_name, '(미등록)') as 상품명,
                   l.sale_price as 판매가, l.coupang_sale_price as 쿠팡가,
                   (l.sale_price - l.coupang_sale_price) as 차이,
                   COALESCE(l.vendor_item_id, '') as VID,
                   l.isbn as ISBN
            FROM listings l
            WHERE l.account_id = :acct_id
              AND l.coupang_status = 'active'
              AND l.coupang_sale_price > 0 AND l.sale_price > 0
              AND l.sale_price != l.coupang_sale_price
            ORDER BY ABS(l.sale_price - l.coupang_sale_price) DESC
        """, {"acct_id": account_id})

        if not _price_diff_df.empty:
            st.caption(f"{len(_price_diff_df)}건의 가격 불일치 발견")
            _pd_gb = GridOptionsBuilder.from_dataframe(_price_diff_df[["상품명", "판매가", "쿠팡가", "차이", "VID"]])
            _pd_gb.configure_selection(selection_mode="multiple", use_checkbox=True)
            _pd_gb.configure_column("상품명", headerCheckboxSelection=True)
            _pd_gb.configure_grid_options(domLayout="normal")
            _pd_grid = AgGrid(
                _price_diff_df[["상품명", "판매가", "쿠팡가", "차이", "VID"]],
                gridOptions=_pd_gb.build(),
                update_on=["selectionChanged"],
                height=300,
                theme="streamlit",
                key="pd_aggrid",
            )
            _pd_selected = _pd_grid["selected_rows"]
            _pd_sel_list = []
            if _pd_selected is not None and len(_pd_selected) > 0:
                _pd_sel_df = _pd_selected if isinstance(_pd_selected, pd.DataFrame) else pd.DataFrame(_pd_selected)
                _pd_sel_list = _pd_sel_df.to_dict("records")

            if _pd_sel_list:
                _pd_confirm = st.checkbox("가격 일괄 수정을 확인합니다", key="pd_confirm")
                if st.button(f"선택 {len(_pd_sel_list)}건 가격 수정 (판매가로)", type="primary", disabled=not _pd_confirm, key="btn_fix_price"):
                    if _wing_client:
                        _pd_prog = st.progress(0, text="가격 수정 중...")
                        _pd_ok, _pd_fail = 0, 0
                        for _pi, _pr in enumerate(_pd_sel_list):
                            _pd_prog.progress((_pi + 1) / len(_pd_sel_list), text=f"[{_pi+1}/{len(_pd_sel_list)}] {str(_pr.get('상품명', ''))[:30]}...")
                            _pr_vid = str(_pr.get("VID", ""))
                            if not _pr_vid:
                                _pd_fail += 1
                                continue
                            # 원본 DF에서 판매가 찾기
                            _pr_match = _price_diff_df[_price_diff_df["VID"] == _pr_vid]
                            _pr_target = int(_pr_match.iloc[0]["판매가"]) if not _pr_match.empty else int(_pr.get("판매가", 0))
                            try:
                                _wing_client.update_price(int(_pr_vid), _pr_target)
                                run_sql("UPDATE listings SET coupang_sale_price=:sp WHERE account_id=:aid AND vendor_item_id=:vid",
                                        {"sp": _pr_target, "aid": account_id, "vid": _pr_vid})
                                _pd_ok += 1
                            except CoupangWingError as e:
                                _pd_fail += 1
                                logger.warning(f"가격 수정 실패 VID={_pr_vid}: {e.message}")
                        _pd_prog.progress(1.0, text="완료!")
                        st.success(f"가격 수정 완료: 성공 {_pd_ok}건, 실패 {_pd_fail}건")
                        query_df.clear()
                        st.rerun()
                    else:
                        st.error("API 키가 설정되지 않았습니다.")
        else:
            st.success("가격 불일치 없음")

        st.divider()

        # ── 재고 부족 목록 ──
        st.markdown("#### 재고 부족 (3개 이하)")
        _low_stock_df = query_df("""
            SELECT l.id, COALESCE(l.product_name, '(미등록)') as 상품명,
                   COALESCE(l.stock_quantity, 0) as 현재재고,
                   COALESCE(l.vendor_item_id, '') as VID,
                   l.isbn as ISBN
            FROM listings l
            WHERE l.account_id = :acct_id
              AND l.coupang_status = 'active'
              AND COALESCE(l.stock_quantity, 0) <= 3
            ORDER BY l.stock_quantity ASC
        """, {"acct_id": account_id})

        if not _low_stock_df.empty:
            st.caption(f"{len(_low_stock_df)}건의 재고 부족")
            _ls_gb = GridOptionsBuilder.from_dataframe(_low_stock_df[["상품명", "현재재고", "VID"]])
            _ls_gb.configure_selection(selection_mode="multiple", use_checkbox=True)
            _ls_gb.configure_column("상품명", headerCheckboxSelection=True)
            _ls_gb.configure_grid_options(domLayout="normal")
            _ls_grid = AgGrid(
                _low_stock_df[["상품명", "현재재고", "VID"]],
                gridOptions=_ls_gb.build(),
                update_on=["selectionChanged"],
                height=300,
                theme="streamlit",
                key="ls_aggrid",
            )
            _ls_selected = _ls_grid["selected_rows"]
            _ls_sel_list = []
            if _ls_selected is not None and len(_ls_selected) > 0:
                _ls_sel_df = _ls_selected if isinstance(_ls_selected, pd.DataFrame) else pd.DataFrame(_ls_selected)
                _ls_sel_list = _ls_sel_df.to_dict("records")

            _refill_qty_col, _refill_btn_col = st.columns([1, 3])
            with _refill_qty_col:
                _refill_qty = st.number_input("리필 수량", value=10, min_value=1, max_value=999, key="refill_qty")

            if _ls_sel_list:
                _ls_confirm = st.checkbox("재고 일괄 리필을 확인합니다", key="ls_confirm")
                if st.button(f"선택 {len(_ls_sel_list)}건 재고 리필 ({_refill_qty}개)", type="primary", disabled=not _ls_confirm, key="btn_refill"):
                    if _wing_client:
                        _ls_prog = st.progress(0, text="재고 리필 중...")
                        _ls_ok, _ls_fail = 0, 0
                        for _li, _lr in enumerate(_ls_sel_list):
                            _ls_prog.progress((_li + 1) / len(_ls_sel_list), text=f"[{_li+1}/{len(_ls_sel_list)}] {str(_lr.get('상품명', ''))[:30]}...")
                            _lr_vid = str(_lr.get("VID", ""))
                            if not _lr_vid:
                                _ls_fail += 1
                                continue
                            try:
                                _wing_client.update_quantity(int(_lr_vid), _refill_qty)
                                run_sql("UPDATE listings SET stock_quantity=:qty WHERE account_id=:aid AND vendor_item_id=:vid",
                                        {"qty": _refill_qty, "aid": account_id, "vid": _lr_vid})
                                _ls_ok += 1
                            except CoupangWingError as e:
                                _ls_fail += 1
                                logger.warning(f"재고 리필 실패 VID={_lr_vid}: {e.message}")
                        _ls_prog.progress(1.0, text="완료!")
                        st.success(f"재고 리필 완료: 성공 {_ls_ok}건, 실패 {_ls_fail}건")
                        query_df.clear()
                        st.rerun()
                    else:
                        st.error("API 키가 설정되지 않았습니다.")
        else:
            st.success("재고 부족 상품 없음")

    # ─────────────────────────────────────────────
    # Tab 3: 등록 현황
    # ─────────────────────────────────────────────
    with pm_tab3:
        st.subheader("등록 현황 (WING API)")

        if _wing_client is None:
            st.warning("이 계정은 WING API 키가 설정되지 않았습니다.")
        else:
            # ── 기간별 조회 ──
            from datetime import date as _pm_date, timedelta as _pm_td
            _tf_col1, _tf_col2, _tf_col3 = st.columns([2, 2, 1])
            with _tf_col1:
                _tf_from = st.date_input("시작일", value=_pm_date.today() - _pm_td(days=30), key="tf_from")
            with _tf_col2:
                _tf_to = st.date_input("종료일", value=_pm_date.today(), key="tf_to")
            with _tf_col3:
                _tf_status = st.selectbox("상태", ["전체", "APPROVED", "WAITING", "REJECTED"], key="tf_status")

            if st.button("조회", type="primary", key="btn_tf_query"):
                try:
                    _tf_from_str = f"{_tf_from.isoformat()}T00:00:00"
                    _tf_to_str = f"{_tf_to.isoformat()}T23:59:59"
                    _tf_status_arg = _tf_status if _tf_status != "전체" else None
                    _tf_result = _wing_client.list_products_by_timeframe(
                        vendor_id=selected_account.get("vendor_id", ""),
                        created_at_from=_tf_from_str,
                        created_at_to=_tf_to_str,
                        max_per_page=100,
                        status=_tf_status_arg,
                    )
                    _tf_data = _tf_result.get("data", _tf_result)
                    _tf_products = []
                    if isinstance(_tf_data, list):
                        _tf_products = _tf_data
                    elif isinstance(_tf_data, dict):
                        _tf_products = _tf_data.get("products", _tf_data.get("data", []))
                    if _tf_products:
                        _tf_rows = []
                        for _tp in _tf_products:
                            _tf_rows.append({
                                "상품ID": _tp.get("sellerProductId", ""),
                                "상품명": _tp.get("sellerProductName", _tp.get("productName", ""))[:60],
                                "상태": _tp.get("status", _tp.get("statusName", "")),
                                "생성일": str(_tp.get("createdAt", ""))[:10],
                                "수정일": str(_tp.get("updatedAt", ""))[:10],
                            })
                        _tf_df = pd.DataFrame(_tf_rows)
                        st.caption(f"{len(_tf_df)}건 조회됨")

                        _tf_gb = GridOptionsBuilder.from_dataframe(_tf_df)
                        _tf_gb.configure_selection(selection_mode="multiple", use_checkbox=True)
                        _tf_gb.configure_column("상품명", headerCheckboxSelection=True)
                        _tf_gb.configure_grid_options(domLayout="normal")
                        _tf_grid = AgGrid(
                            _tf_df,
                            gridOptions=_tf_gb.build(),
                            update_on=["selectionChanged"],
                            height=350,
                            theme="streamlit",
                            key="tf_aggrid",
                        )

                        # ── 승인 요청 ──
                        _tf_sel = _tf_grid["selected_rows"]
                        _tf_sel_list = []
                        if _tf_sel is not None and len(_tf_sel) > 0:
                            _tf_sel_df = _tf_sel if isinstance(_tf_sel, pd.DataFrame) else pd.DataFrame(_tf_sel)
                            _tf_sel_list = _tf_sel_df.to_dict("records")

                        if _tf_sel_list:
                            _ap_confirm = st.checkbox("승인 요청을 확인합니다", key="ap_confirm")
                            if st.button(f"선택 {len(_tf_sel_list)}건 승인 요청", type="primary", disabled=not _ap_confirm, key="btn_approve"):
                                _ap_prog = st.progress(0, text="승인 요청 중...")
                                _ap_ok, _ap_fail = 0, 0
                                for _ai, _ar in enumerate(_tf_sel_list):
                                    _ap_prog.progress((_ai + 1) / len(_tf_sel_list), text=f"[{_ai+1}/{len(_tf_sel_list)}]")
                                    _ar_id = _ar.get("상품ID", "")
                                    if not _ar_id:
                                        _ap_fail += 1
                                        continue
                                    try:
                                        _wing_client.approve_product(int(_ar_id))
                                        _ap_ok += 1
                                    except CoupangWingError as e:
                                        _ap_fail += 1
                                        logger.warning(f"승인 요청 실패 ID={_ar_id}: {e.message}")
                                _ap_prog.progress(1.0, text="완료!")
                                st.success(f"승인 요청 완료: 성공 {_ap_ok}건, 실패 {_ap_fail}건")

                            # ── 반려 상품 상세 보기 ──
                            _last_sel = _tf_sel_list[-1]
                            if str(_last_sel.get("상태", "")).upper() in ("REJECTED", "반려"):
                                _rej_id = _last_sel.get("상품ID", "")
                                if _rej_id:
                                    with st.expander(f"반려 상품 상세: {_last_sel.get('상품명', '')}"):
                                        try:
                                            _rej_detail = _wing_client.get_product_partial(int(_rej_id))
                                            st.json(_rej_detail)
                                        except CoupangWingError as e:
                                            st.error(f"상세 조회 실패: {e.message}")
                    else:
                        st.info("해당 기간에 등록된 상품이 없습니다.")
                except CoupangWingError as e:
                    st.error(f"API 오류: {e.message}")
                except Exception as e:
                    st.error(f"조회 실패: {e}")

    # ─────────────────────────────────────────────
    # Tab 4: 상태 이력
    # ─────────────────────────────────────────────
    with pm_tab4:
        st.subheader("상품 상태 변경 이력")

        if _wing_client is None:
            st.warning("이 계정은 WING API 키가 설정되지 않았습니다.")
        else:
            # 상품 선택 (DB listings 또는 직접 입력)
            _hist_listings = query_df("""
                SELECT COALESCE(l.product_name, '(미등록)') || ' [' || COALESCE(l.coupang_product_id, '-') || ']' as label,
                       l.coupang_product_id as pid
                FROM listings l
                WHERE l.account_id = :acct_id AND l.coupang_product_id IS NOT NULL AND l.coupang_product_id != ''
                ORDER BY l.uploaded_at DESC LIMIT 100
            """, {"acct_id": account_id})

            _hist_col1, _hist_col2 = st.columns([3, 1])
            with _hist_col1:
                _hist_options = _hist_listings["label"].tolist() if not _hist_listings.empty else []
                _hist_sel = st.selectbox("상품 선택", ["(직접 입력)"] + _hist_options, key="hist_sel")
            with _hist_col2:
                _hist_manual = st.text_input("상품 ID 직접 입력", key="hist_manual")

            _hist_pid = ""
            if _hist_sel != "(직접 입력)" and not _hist_listings.empty:
                _hist_match = _hist_listings[_hist_listings["label"] == _hist_sel]
                if not _hist_match.empty:
                    _hist_pid = str(_hist_match.iloc[0]["pid"])
            if _hist_manual:
                _hist_pid = _hist_manual.strip()

            if st.button("이력 조회", type="primary", key="btn_history", disabled=not _hist_pid):
                try:
                    _hist_result = _wing_client.get_product_history(int(_hist_pid))
                    _hist_data = _hist_result.get("data", _hist_result)
                    _hist_items = []
                    if isinstance(_hist_data, list):
                        _hist_items = _hist_data
                    elif isinstance(_hist_data, dict):
                        _hist_items = _hist_data.get("histories", _hist_data.get("data", []))

                    if _hist_items:
                        _hist_rows = []
                        for _h in _hist_items:
                            _hist_rows.append({
                                "변경일시": str(_h.get("createdAt", _h.get("updatedAt", "")))[:19],
                                "이전상태": _h.get("previousStatus", _h.get("beforeStatus", "-")),
                                "변경상태": _h.get("currentStatus", _h.get("afterStatus", "-")),
                                "사유": _h.get("reason", _h.get("message", "-")),
                            })
                        st.dataframe(pd.DataFrame(_hist_rows), width="stretch", hide_index=True)
                    else:
                        st.info("변경 이력이 없습니다.")
                        st.json(_hist_result)
                except CoupangWingError as e:
                    st.error(f"API 오류: {e.message}")
                except Exception as e:
                    st.error(f"이력 조회 실패: {e}")


# ═══════════════════════════════════════
# 신규 등록
# ═══════════════════════════════════════
elif page == "신규 등록":
    st.title(f"{selected_account_name} 신규 등록")

    if selected_account is None:
        st.warning("왼쪽에서 계정을 선택하세요.")
        st.stop()

    account_id = int(selected_account["id"])
    outbound_code = selected_account.get("outbound_shipping_code", "")
    return_code = selected_account.get("return_center_code", "")

    if not outbound_code or not return_code:
        st.error("출고지/반품지 코드 미설정")
        st.stop()

    # 미등록 상품 전체 (registration_status + supply_rate 포함)
    ready = query_df(f"""
        SELECT p.id as product_id, b.title, b.author, b.publisher_name,
               b.isbn, b.image_url, b.list_price, p.sale_price, p.net_margin,
               p.shipping_policy, p.supply_rate, b.year, b.description,
               COALESCE(p.registration_status, 'approved') as registration_status
        FROM products p
        JOIN books b ON p.book_id = b.id
        WHERE p.status = 'ready' AND p.can_upload_single = 1
          AND p.isbn NOT IN (
              SELECT COALESCE(l.isbn, '') FROM listings l
              WHERE l.account_id = {account_id} AND l.isbn IS NOT NULL
          )
          AND b.title NOT IN (
              SELECT COALESCE(l.product_name, '') FROM listings l
              WHERE l.account_id = {account_id} AND l.product_name IS NOT NULL
          )
        ORDER BY p.shipping_policy DESC, p.net_margin ASC
    """)

    # ── 마진/배송비 실시간 재계산 ──
    def _recalc_margin(row):
        """출판사 supply_rate 기준 마진/배송정책 재계산
        - free: 셀러가 배송비 부담 → 순마진 = 마진 - 택배비(2,300)
        - paid: 소비자가 배송비 부담 → 순마진 = 마진 (배송비 차감 없음)
        """
        lp = int(row.get("list_price", 0) or 0)
        sr = float(row.get("supply_rate", 0.65) or 0.65)
        sp = int(lp * BOOK_DISCOUNT_RATE)
        supply_cost = int(lp * sr)
        fee = int(sp * COUPANG_FEE_RATE)
        margin = sp - supply_cost - fee  # 배송비 제외 순수 마진
        # 배송정책 판단: 셀러가 배송비 부담한다고 가정한 최악 마진 기준
        worst_net = margin - DEFAULT_SHIPPING_COST
        if worst_net >= FREE_SHIPPING_THRESHOLD:
            policy = "free"
            actual_net = worst_net  # 셀러 부담
        elif worst_net >= 0:
            policy = "paid"
            actual_net = margin  # 소비자가 배송비 부담 → 배송비 차감 없음
        else:
            policy = "bundle_required"
            actual_net = worst_net
        return pd.Series({
            "calc_sale": sp, "calc_supply": supply_cost, "calc_fee": fee,
            "calc_margin": margin, "calc_net": actual_net, "calc_ship": policy,
        })

    if not ready.empty:
        _calc = ready.apply(_recalc_margin, axis=1)
        ready = pd.concat([ready, _calc], axis=1)
        # 배송비 변경 여부 표시
        ready["ship_changed"] = ready["shipping_policy"] != ready["calc_ship"]

    total_registered = query_df(f"SELECT COUNT(*) as c FROM listings WHERE account_id = {account_id}")
    reg_cnt = int(total_registered.iloc[0]["c"]) if not total_registered.empty else 0

    # KPI 메트릭 (승인 상태별)
    pending_cnt = len(ready[ready["registration_status"] == "pending_review"]) if not ready.empty else 0
    approved_cnt = len(ready[ready["registration_status"] == "approved"]) if not ready.empty else 0
    rejected_cnt = len(ready[ready["registration_status"] == "rejected"]) if not ready.empty else 0
    ship_changed_cnt = int(ready["ship_changed"].sum()) if not ready.empty and "ship_changed" in ready.columns else 0

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("등록 가능 (승인됨)", f"{approved_cnt}건")
    k2.metric("검토 대기", f"{pending_cnt}건")
    k3.metric("거부됨", f"{rejected_cnt}건")
    k4.metric("이미 등록됨", f"{reg_cnt:,}건")
    k5.metric("배송비 변경 필요", f"{ship_changed_cnt}건", delta=f"{ship_changed_cnt}" if ship_changed_cnt > 0 else None, delta_color="inverse")

    # ── 배송비 재계산 요약 + 일괄 적용 ──
    if not ready.empty and ship_changed_cnt > 0:
        with st.container(border=True):
            st.markdown(f"**배송비 재계산 결과** — {ship_changed_cnt}건의 배송정책이 현재 DB와 다릅니다")
            _ship_summary = ready[ready["ship_changed"]].groupby(["shipping_policy", "calc_ship"]).size().reset_index(name="건수")
            _ship_summary.columns = ["현재 배송정책", "재계산 결과", "건수"]
            _ship_label_map = {"free": "무료", "paid": "유료(2,500)", "bundle_required": "묶음필수"}
            _ship_summary["현재 배송정책"] = _ship_summary["현재 배송정책"].map(_ship_label_map)
            _ship_summary["재계산 결과"] = _ship_summary["재계산 결과"].map(_ship_label_map)
            st.dataframe(_ship_summary, hide_index=True, width="stretch")

            if st.button(f"배송비 재계산 DB 일괄 적용 ({ship_changed_cnt}건)", type="primary", key="btn_recalc_apply"):
                _update_cnt = 0
                for _, _r in ready[ready["ship_changed"]].iterrows():
                    try:
                        run_sql(
                            "UPDATE products SET sale_price=:sp, net_margin=:nm, shipping_policy=:sh WHERE id=:id",
                            {"sp": int(_r["calc_sale"]), "nm": int(_r["calc_net"]),
                             "sh": _r["calc_ship"], "id": int(_r["product_id"])}
                        )
                        _update_cnt += 1
                    except Exception as _e:
                        logger.warning(f"재계산 적용 실패 (pid={_r['product_id']}): {_e}")
                st.success(f"배송비 재계산 적용 완료: {_update_cnt}건")
                st.cache_data.clear()
                st.rerun()

    # 알라딘 크롤링
    with st.expander("알라딘에서 새 도서 검색"):
        cr_col1, cr_col2 = st.columns([3, 1])
        with cr_col1:
            crawl_max = st.number_input("출판사당 최대 검색 수", value=20, step=10, min_value=5, max_value=50, key="cr_max")
        with cr_col2:
            btn_crawl = st.button("크롤링 시작", type="primary", key="btn_crawl", width="stretch")
        if btn_crawl:
            from scripts.franchise_sync import FranchiseSync
            sync = FranchiseSync()
            try:
                crawl_progress = st.progress(0, text="출판사별 알라딘 검색 중...")
                crawl_result = sync.crawl_by_publisher(
                    max_per_publisher=crawl_max,
                    progress_callback=lambda cur, tot, msg: crawl_progress.progress(cur / tot if tot > 0 else 0, text=msg),
                )
                crawl_progress.progress(0.9, text="마진 분석 중...")
                analyze_result = sync.analyze_products(crawl_result["books"])
                crawl_progress.progress(1.0, text="완료!")
                st.success(f"검색 {crawl_result['searched']}개 → 신규 {crawl_result['new']}개, Product {analyze_result['created']}개")
                query_df.clear()
                st.rerun()
            except Exception as e:
                st.error(f"크롤링 오류: {e}")
            finally:
                sync.close()

    st.divider()

    if ready.empty:
        st.info("등록 가능한 신규 상품이 없습니다. 알라딘 크롤링을 해보세요.")
        st.stop()

    # 필터 (승인 상태 + 출판사 + 최소 마진)
    cf1, cf2, cf3 = st.columns(3)
    with cf1:
        status_options = ["전체", "검토 대기", "승인됨", "거부됨"]
        status_f = st.selectbox("등록 상태", status_options, key="nr_status")
    with cf2:
        pubs = ["전체"] + sorted(ready["publisher_name"].dropna().unique().tolist())
        pub_f = st.selectbox("출판사", pubs, key="nr_pub")
    with cf3:
        min_m = st.number_input("최소 마진(원)", value=0, step=500, key="nr_mm")

    _status_map = {"검토 대기": "pending_review", "승인됨": "approved", "거부됨": "rejected"}
    filtered = ready.copy()
    if status_f != "전체":
        filtered = filtered[filtered["registration_status"] == _status_map[status_f]]
    if pub_f != "전체":
        filtered = filtered[filtered["publisher_name"] == pub_f]
    if min_m > 0:
        filtered = filtered[filtered["net_margin"] >= min_m]

    if filtered.empty:
        st.info("필터 조건에 맞는 상품이 없습니다.")
        st.stop()

    # ── 일괄 승인/거부 버튼 (그리드 위) ──
    ba1, ba2, ba3 = st.columns([2, 1, 1])
    with ba1:
        st.markdown(f"**조회: {len(filtered)}건**")

    # ── 상품 테이블 (AgGrid: 체크박스 + 등록상태) ──
    display = filtered.copy()

    _status_label = {"pending_review": "검토 대기", "approved": "승인", "rejected": "거부"}
    display["등록상태"] = display["registration_status"].map(_status_label).fillna("검토 대기")

    _ship_label = {"free": "무료", "paid": "유료(2,500)", "bundle_required": "묶음필수"}
    display["배송비"] = display["shipping_policy"].map(_ship_label).fillna(display["shipping_policy"])
    display["재계산배송"] = display["calc_ship"].map(_ship_label).fillna("") if "calc_ship" in display.columns else ""
    display["공급율"] = (display["supply_rate"] * 100).round(0).astype(int).astype(str) + "%" if "supply_rate" in display.columns else ""
    display["재계산마진"] = display["calc_net"].astype(int) if "calc_net" in display.columns else 0
    display["변경"] = display["ship_changed"].map({True: "⚠", False: ""}) if "ship_changed" in display.columns else ""

    nr_grid_df = display[["title", "publisher_name", "isbn", "list_price", "sale_price", "net_margin", "공급율", "배송비", "재계산마진", "재계산배송", "변경", "등록상태", "year"]].rename(columns={
        "title": "제목", "publisher_name": "출판사", "isbn": "ISBN",
        "list_price": "정가", "sale_price": "판매가", "net_margin": "순마진", "year": "연도",
    })
    nr_gb = GridOptionsBuilder.from_dataframe(nr_grid_df)
    nr_gb.configure_selection(selection_mode="multiple", use_checkbox=True)
    nr_gb.configure_column("제목", headerCheckboxSelection=True, minWidth=200)
    nr_gb.configure_column("배송비", width=90)
    nr_gb.configure_column("재계산배송", width=90)
    nr_gb.configure_column("재계산마진", width=90)
    nr_gb.configure_column("공급율", width=70)
    nr_gb.configure_column("변경", width=50)
    nr_gb.configure_column("등록상태", width=80)
    nr_gb.configure_grid_options(domLayout="normal", suppressRowClickSelection=False)
    nr_grid = AgGrid(
        nr_grid_df,
        gridOptions=nr_gb.build(),
        update_on=["selectionChanged"],
        height=400,
        theme="streamlit",
        key="nr_aggrid",
    )

    nr_selected = nr_grid["selected_rows"]
    sel_idx = []
    if nr_selected is not None and len(nr_selected) > 0:
        _sel_df = nr_selected if isinstance(nr_selected, pd.DataFrame) else pd.DataFrame(nr_selected)
        sel_titles = _sel_df["제목"].tolist()
        sel_idx = [i for i, t in enumerate(display["title"]) if t in sel_titles]
    sel_cnt = len(sel_idx)

    # ── 일괄 승인/거부 버튼 ──
    st.markdown(f"**선택: {sel_cnt}건**")
    ap1, ap2, ap3 = st.columns([1, 1, 4])
    with ap1:
        btn_bulk_approve = st.button("일괄 승인", type="primary", disabled=(sel_cnt == 0), key="btn_bulk_approve")
    with ap2:
        btn_bulk_reject = st.button("일괄 거부", disabled=(sel_cnt == 0), key="btn_bulk_reject")

    if btn_bulk_approve and sel_cnt > 0:
        pids = [int(display.iloc[i]["product_id"]) for i in sel_idx]
        placeholders = ",".join(str(p) for p in pids)
        run_sql(f"UPDATE products SET registration_status = 'approved' WHERE id IN ({placeholders})")
        st.success(f"{sel_cnt}건 승인 완료")
        st.cache_data.clear()
        st.rerun()

    if btn_bulk_reject and sel_cnt > 0:
        pids = [int(display.iloc[i]["product_id"]) for i in sel_idx]
        placeholders = ",".join(str(p) for p in pids)
        run_sql(f"UPDATE products SET registration_status = 'rejected' WHERE id IN ({placeholders})")
        st.success(f"{sel_cnt}건 거부 완료")
        st.cache_data.clear()
        st.rerun()

    # ── 행 클릭 → 상세 보기 ──
    if nr_selected is not None and len(nr_selected) > 0:
        _sel_row = nr_selected.iloc[0] if hasattr(nr_selected, "iloc") else pd.Series(nr_selected[0])
        nr_sel_title = _sel_row["제목"]
        _match = display[display["title"] == nr_sel_title]
        if not _match.empty:
            nr_sel = _match.iloc[0]
            book_id_row = query_df("SELECT id, image_url, description, author FROM books WHERE isbn = :isbn LIMIT 1", {"isbn": nr_sel["isbn"]}) if nr_sel["isbn"] else pd.DataFrame()

            st.divider()
            pv1, pv2 = st.columns([1, 3])
            with pv1:
                img = book_id_row.iloc[0]["image_url"] if not book_id_row.empty and book_id_row.iloc[0]["image_url"] else ""
                if img:
                    try:
                        st.image(img, width=150)
                    except Exception:
                        st.markdown('<div style="width:150px;height:200px;background:#f0f0f0;display:flex;align-items:center;justify-content:center;border-radius:8px;color:#999;font-size:40px;">📖</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div style="width:150px;height:200px;background:#f0f0f0;display:flex;align-items:center;justify-content:center;border-radius:8px;color:#999;font-size:40px;">📖</div>', unsafe_allow_html=True)
            with pv2:
                st.markdown(f"**{nr_sel['title']}**")
                author = book_id_row.iloc[0]["author"] if not book_id_row.empty else ""
                _cur_status = nr_sel.get("등록상태", "검토 대기")
                st.markdown(f"{author or ''} | {nr_sel['publisher_name']} | ISBN: `{nr_sel['isbn']}` | 상태: **{_cur_status}**")
                st.markdown(f"정가 {int(nr_sel['list_price']):,}원 → 판매가 {int(nr_sel['sale_price']):,}원 | 순마진 **{int(nr_sel['net_margin']):,}원**")

                # 개별 승인/거부 버튼
                _pid = int(nr_sel["product_id"])
                iv1, iv2, iv3 = st.columns([1, 1, 4])
                with iv1:
                    if st.button("승인", type="primary", key=f"approve_{_pid}"):
                        run_sql("UPDATE products SET registration_status = 'approved' WHERE id = :id", {"id": _pid})
                        st.success("승인 완료")
                        st.cache_data.clear()
                        st.rerun()
                with iv2:
                    if st.button("거부", key=f"reject_{_pid}"):
                        run_sql("UPDATE products SET registration_status = 'rejected' WHERE id = :id", {"id": _pid})
                        st.success("거부 완료")
                        st.cache_data.clear()
                        st.rerun()

            with st.expander("수정 / 삭제"):
                bid = int(book_id_row.iloc[0]["id"]) if not book_id_row.empty else None
                pid = int(nr_sel["product_id"])
                if bid:
                    with st.form("nr_edit_form"):
                        ed1, ed2, ed3 = st.columns(3)
                        with ed1:
                            ed_sale = st.number_input("판매가", value=int(nr_sel["sale_price"]), step=100)
                        with ed2:
                            ed_price = st.number_input("정가", value=int(nr_sel["list_price"]), step=100)
                        with ed3:
                            ed_ship = st.selectbox("배송", ["free", "paid"],
                                                   index=0 if nr_sel["shipping_policy"] == "free" else 1)
                        if st.form_submit_button("저장", type="primary"):
                            try:
                                run_sql("UPDATE books SET list_price=:lp WHERE id=:id", {"lp": ed_price, "id": bid})
                                _sr = float(nr_sel.get("supply_rate", 0.65) or 0.65)
                                _supply_cost = int(ed_price * _sr)
                                _fee = int(ed_sale * COUPANG_FEE_RATE)
                                nm = ed_sale - _supply_cost - _fee - DEFAULT_SHIPPING_COST
                                run_sql("UPDATE products SET sale_price=:sp, net_margin=:nm, shipping_policy=:sh WHERE id=:id",
                                        {"sp": ed_sale, "nm": int(nm), "sh": ed_ship, "id": pid})
                                st.success("저장 완료")
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"저장 실패: {e}")

                    del_confirm = st.text_input("삭제하려면 '삭제' 입력", key="nr_del_confirm")
                    if st.button("삭제", type="primary", disabled=(del_confirm != "삭제"), key="nr_del_btn"):
                        try:
                            run_sql("DELETE FROM products WHERE id=:id", {"id": pid})
                            if not book_id_row.empty:
                                run_sql("DELETE FROM books WHERE id=:id", {"id": int(book_id_row.iloc[0]["id"])})
                            st.success("삭제 완료")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"삭제 실패: {e}")

    st.divider()

    # 등록 버튼 (승인된 상품만 업로드 가능)
    _approved_sel_idx = [i for i in sel_idx if display.iloc[i].get("registration_status") == "approved"]
    _approved_cnt = len(_approved_sel_idx)
    _unapproved_cnt = sel_cnt - _approved_cnt

    cb1, cb2, cb3 = st.columns([2, 1, 3])
    with cb1:
        _label = f"**선택: {sel_cnt}건** (승인됨: {_approved_cnt}건)"
        if _unapproved_cnt > 0:
            _label += f" | 미승인 {_unapproved_cnt}건 제외"
        st.markdown(_label)
    with cb2:
        dry = st.checkbox("Dry Run", value=True, key="dry", help="실제 등록 안 하고 확인만")
    with cb3:
        btn = st.button(
            f"{'테스트' if dry else '쿠팡에 등록'} ({_approved_cnt}건)",
            type="primary", disabled=(_approved_cnt == 0),
        )

    if btn and _approved_cnt > 0:
        client = create_wing_client(selected_account)
        if client is None:
            st.error("API 키 미설정")
            st.stop()

        uploader = CoupangAPIUploader(client, vendor_user_id=selected_account_name)
        progress = st.progress(0, text="준비 중...")
        result_box = st.container()
        ok_list, fail_list = [], []

        for i, idx in enumerate(_approved_sel_idx):
            row = display.iloc[idx]
            pd_data = product_to_upload_data(row)
            name = pd_data["product_name"]
            progress.progress((i+1)/_approved_cnt, text=f"[{i+1}/{_approved_cnt}] {name[:30]}...")

            if dry:
                try:
                    payload = uploader.build_product_payload(pd_data, outbound_code, return_code)
                    ok_list.append({"제목": name[:40], "ISBN": pd_data["isbn"], "결과": "OK"})
                except Exception as e:
                    fail_list.append({"제목": name[:40], "결과": str(e)[:80]})
            else:
                res = uploader.upload_product(pd_data, outbound_code, return_code)
                if res["success"]:
                    sid = res["seller_product_id"]
                    ok_list.append({"제목": name[:40], "쿠팡ID": sid, "결과": "성공"})
                    try:
                        with engine.connect() as conn:
                            conn.execute(text("""
                                INSERT OR IGNORE INTO listings
                                (account_id, product_type, product_id, isbn, coupang_product_id,
                                 coupang_status, sale_price, original_price, product_name,
                                 shipping_policy, upload_method, uploaded_at)
                                VALUES (:aid, 'single', :pid, :isbn, :cid, 'active', :sp, :op, :pn, :ship, 'api', :now)
                            """), {
                                "aid": account_id, "pid": int(row["product_id"]),
                                "isbn": pd_data["isbn"], "cid": sid,
                                "sp": pd_data["sale_price"], "op": pd_data["original_price"],
                                "pn": name, "ship": pd_data["shipping_policy"],
                                "now": datetime.now().isoformat(),
                            })
                            conn.commit()
                    except Exception as db_e:
                        logger.warning(f"DB 저장 실패: {db_e}")
                else:
                    fail_list.append({"제목": name[:40], "결과": res["message"][:80]})

        progress.progress(1.0, text="완료!")
        with result_box:
            if ok_list:
                st.success(f"성공: {len(ok_list)}건")
                st.dataframe(pd.DataFrame(ok_list), width="stretch", hide_index=True)
            if fail_list:
                st.error(f"실패: {len(fail_list)}건")
                st.dataframe(pd.DataFrame(fail_list), width="stretch", hide_index=True)
        query_df.clear()


# ═══════════════════════════════════════
# 수동 등록
# ═══════════════════════════════════════
elif page == "수동 등록":
    st.title("수동 상품 등록")
    st.caption("DB에 없는 상품도 직접 정보를 입력하여 여러 계정에 한번에 등록")

    # ── CSS 스타일 ──
    st.markdown("""
    <style>
    .section-header {
        display: flex; align-items: center; gap: 10px;
        border-bottom: 2px solid #1976D2; padding-bottom: 8px; margin-bottom: 16px;
    }
    .section-badge {
        background: #1976D2; color: white; border-radius: 50%;
        width: 28px; height: 28px; display: flex; align-items: center; justify-content: center;
        font-weight: bold; font-size: 14px; flex-shrink: 0;
    }
    .section-title { font-size: 18px; font-weight: 600; color: #1976D2; margin: 0; }
    .tag-pill {
        display: inline-block; background: #E3F2FD; color: #1565C0;
        border-radius: 12px; padding: 2px 10px; margin: 2px 3px; font-size: 13px;
    }
    .margin-box {
        background: #F5F5F5; border-radius: 8px; padding: 12px 16px;
        border-left: 4px solid #1976D2; margin-top: 8px;
    }
    .field-required { color: #D32F2F; font-weight: bold; }
    .check-ok { color: #2E7D32; } .check-fail { color: #D32F2F; }
    </style>
    """, unsafe_allow_html=True)

    def _section_header(num, title):
        st.markdown(f'''<div class="section-header">
            <div class="section-badge">{num}</div>
            <p class="section-title">{title}</p>
        </div>''', unsafe_allow_html=True)

    # ── WING 클라이언트 헬퍼 (카테고리 API용) ──
    def _get_any_wing_client():
        """WING API 활성 계정 중 하나의 클라이언트 반환"""
        _accs = accounts_df[(accounts_df["wing_api_enabled"] == 1)].to_dict("records")
        if _accs:
            return create_wing_client(_accs[0]), _accs[0]
        return None, None

    # ══════════════════════════════════════
    # 섹션 1: 카테고리 선택
    # ══════════════════════════════════════
    with st.container(border=True):
        _section_header(1, "카테고리 선택")

        _cat_tab1, _cat_tab2 = st.tabs(["직접 입력 / 추천", "카테고리 찾기"])

        # ── 탭1: 직접 입력 + AI 추천 ──
        with _cat_tab1:
            _cat_row1_c1, _cat_row1_c2, _cat_row1_c3 = st.columns([2, 1, 2])
            with _cat_row1_c1:
                _m_category = st.text_input(
                    "카테고리 코드 *", value="76236", key="m_form_category",
                    help="쿠팡 leaf 카테고리 코드 (기본: 76236 고등교재)",
                )
            with _cat_row1_c2:
                st.markdown("<br>", unsafe_allow_html=True)
                _cat_rec_btn = st.button("AI 추천", key="btn_cat_recommend", type="secondary")
            with _cat_row1_c3:
                st.markdown("<br>", unsafe_allow_html=True)
                _cat_val_btn = st.button("유효성 검사", key="btn_cat_validate")

            # AI 추천 실행
            if _cat_rec_btn:
                _title_for_rec = st.session_state.get("m_title", "")
                if _title_for_rec:
                    _rec_client, _ = _get_any_wing_client()
                    if _rec_client:
                        try:
                            _rec_result = _rec_client.recommend_category(_title_for_rec)
                            _rec_data = _rec_result.get("data", {})
                            _rec_type = _rec_data.get("autoCategorizationPredictionResultType", "")
                            _rec_code = str(_rec_data.get("predictedCategoryId", ""))
                            _rec_name = _rec_data.get("predictedCategoryName", "")
                            if _rec_type == "SUCCESS" and _rec_code:
                                st.session_state["m_form_category"] = _rec_code
                                st.session_state["_cat_rec_name"] = _rec_name
                                st.success(f"추천 카테고리: **{_rec_code}** — {_rec_name}")
                                st.rerun()
                            else:
                                st.warning(f"추천 실패: {_rec_type} — {_rec_data.get('comment', '정보 부족')}")
                        except Exception as e:
                            st.error(f"카테고리 추천 오류: {e}")
                    else:
                        st.error("WING API 활성 계정이 없습니다.")
                else:
                    st.warning("상품명을 먼저 입력해주세요 (섹션 2)")

            # 유효성 검사 실행
            if _cat_val_btn and _m_category:
                _val_client, _ = _get_any_wing_client()
                if _val_client:
                    try:
                        _val_result = _val_client.validate_category(_m_category)
                        _val_data = _val_result.get("data", False)
                        if _val_data is True:
                            st.success(f"**{_m_category}** — 유효한 leaf 카테고리입니다")
                            st.session_state["_cat_valid"] = True
                        else:
                            st.error(f"**{_m_category}** — 사용 불가능한 카테고리입니다")
                            st.session_state["_cat_valid"] = False
                    except CoupangWingError as e:
                        _err_msg = str(e)
                        if "leaf category code가 아닙니다" in _err_msg:
                            st.error(f"**{_m_category}** — leaf 카테고리가 아닙니다. 하위 카테고리를 선택하세요.")
                            st.caption(f"상세: {_err_msg}")
                        else:
                            st.error(f"유효성 검사 오류: {e}")
                        st.session_state["_cat_valid"] = False
                    except Exception as e:
                        st.error(f"유효성 검사 오류: {e}")

            # 선택된 카테고리 요약
            _cat_display_name = st.session_state.get("_cat_rec_name", "") or BOOK_CATEGORY_MAP.get(_m_category, "")
            if _cat_display_name:
                _valid_icon = ""
                if st.session_state.get("_cat_valid") is True:
                    _valid_icon = '<span class="check-ok">&#10004; 유효</span>'
                elif st.session_state.get("_cat_valid") is False:
                    _valid_icon = '<span class="check-fail">&#10008; 무효</span>'
                st.markdown(
                    f"선택: **{_m_category}** — {_cat_display_name} {_valid_icon}",
                    unsafe_allow_html=True,
                )

        # ── 탭2: 카테고리 드릴다운 ──
        with _cat_tab2:
            st.caption("카테고리를 단계별로 선택합니다. (API 호출 필요)")
            _browse_client, _ = _get_any_wing_client()
            if _browse_client:
                # Level 1: 최상위 카테고리
                if "_cat_L1_data" not in st.session_state:
                    try:
                        _L1_result = _browse_client.get_display_categories("0")
                        _L1_data = _L1_result.get("data", {})
                        _L1_children = _L1_data.get("child", [])
                        st.session_state["_cat_L1_data"] = _L1_children
                    except Exception as e:
                        st.error(f"최상위 카테고리 조회 실패: {e}")
                        st.session_state["_cat_L1_data"] = []

                _L1_children = st.session_state.get("_cat_L1_data", [])
                if _L1_children:
                    _L1_names = ["선택하세요"] + [c["name"] for c in _L1_children if c.get("status") == "ACTIVE"]
                    _L1_codes = [""] + [str(c["displayItemCategoryCode"]) for c in _L1_children if c.get("status") == "ACTIVE"]

                    _bc1, _bc2, _bc3, _bc4 = st.columns(4)
                    with _bc1:
                        _sel_L1_idx = st.selectbox("대분류", range(len(_L1_names)), format_func=lambda i: _L1_names[i], key="cat_L1")
                    _sel_L1_code = _L1_codes[_sel_L1_idx] if _sel_L1_idx > 0 else ""

                    # Level 2
                    _L2_names, _L2_codes = ["선택하세요"], [""]
                    if _sel_L1_code:
                        _L2_key = f"_cat_L2_{_sel_L1_code}"
                        if _L2_key not in st.session_state:
                            try:
                                _L2_result = _browse_client.get_display_categories(_sel_L1_code)
                                _L2_data = _L2_result.get("data", {})
                                st.session_state[_L2_key] = _L2_data.get("child", [])
                            except Exception:
                                st.session_state[_L2_key] = []
                        for _c in st.session_state.get(_L2_key, []):
                            if _c.get("status") == "ACTIVE":
                                _L2_names.append(_c["name"])
                                _L2_codes.append(str(_c["displayItemCategoryCode"]))

                    with _bc2:
                        _sel_L2_idx = st.selectbox("중분류", range(len(_L2_names)), format_func=lambda i: _L2_names[i], key="cat_L2")
                    _sel_L2_code = _L2_codes[_sel_L2_idx] if _sel_L2_idx > 0 else ""

                    # Level 3
                    _L3_names, _L3_codes = ["선택하세요"], [""]
                    if _sel_L2_code:
                        _L3_key = f"_cat_L3_{_sel_L2_code}"
                        if _L3_key not in st.session_state:
                            try:
                                _L3_result = _browse_client.get_display_categories(_sel_L2_code)
                                _L3_data = _L3_result.get("data", {})
                                st.session_state[_L3_key] = _L3_data.get("child", [])
                            except Exception:
                                st.session_state[_L3_key] = []
                        for _c in st.session_state.get(_L3_key, []):
                            if _c.get("status") == "ACTIVE":
                                _L3_names.append(_c["name"])
                                _L3_codes.append(str(_c["displayItemCategoryCode"]))

                    with _bc3:
                        _sel_L3_idx = st.selectbox("소분류", range(len(_L3_names)), format_func=lambda i: _L3_names[i], key="cat_L3")
                    _sel_L3_code = _L3_codes[_sel_L3_idx] if _sel_L3_idx > 0 else ""

                    # Level 4
                    _L4_names, _L4_codes = ["선택하세요"], [""]
                    if _sel_L3_code:
                        _L4_key = f"_cat_L4_{_sel_L3_code}"
                        if _L4_key not in st.session_state:
                            try:
                                _L4_result = _browse_client.get_display_categories(_sel_L3_code)
                                _L4_data = _L4_result.get("data", {})
                                st.session_state[_L4_key] = _L4_data.get("child", [])
                            except Exception:
                                st.session_state[_L4_key] = []
                        for _c in st.session_state.get(_L4_key, []):
                            if _c.get("status") == "ACTIVE":
                                _L4_names.append(_c["name"])
                                _L4_codes.append(str(_c["displayItemCategoryCode"]))

                    with _bc4:
                        _sel_L4_idx = st.selectbox("세분류", range(len(_L4_names)), format_func=lambda i: _L4_names[i], key="cat_L4")
                    _sel_L4_code = _L4_codes[_sel_L4_idx] if _sel_L4_idx > 0 else ""

                    # 최하위 선택된 코드를 카테고리로 적용
                    _final_browse_code = _sel_L4_code or _sel_L3_code or _sel_L2_code or _sel_L1_code
                    if _final_browse_code:
                        _browse_path_parts = []
                        if _sel_L1_idx > 0:
                            _browse_path_parts.append(_L1_names[_sel_L1_idx])
                        if _sel_L2_idx > 0:
                            _browse_path_parts.append(_L2_names[_sel_L2_idx])
                        if _sel_L3_idx > 0:
                            _browse_path_parts.append(_L3_names[_sel_L3_idx])
                        if _sel_L4_idx > 0:
                            _browse_path_parts.append(_L4_names[_sel_L4_idx])
                        _browse_path = " > ".join(_browse_path_parts)
                        st.info(f"선택 경로: **{_browse_path}** (코드: {_final_browse_code})")
                        if st.button("이 카테고리 적용", key="btn_apply_browse_cat"):
                            st.session_state["m_form_category"] = _final_browse_code
                            st.session_state["_cat_rec_name"] = _browse_path
                            st.session_state["_cat_valid"] = None
                            st.rerun()
            else:
                st.warning("WING API 활성 계정이 없어 카테고리 탐색을 사용할 수 없습니다.")

        # ── 카테고리 메타정보 미리보기 ──
        if _m_category:
            with st.expander("카테고리 메타정보 조회", expanded=False):
                _meta_client, _ = _get_any_wing_client()
                if _meta_client:
                    _meta_cache_key = f"_cat_meta_{_m_category}"
                    if st.button("메타정보 조회", key="btn_cat_meta"):
                        try:
                            _meta_result = _meta_client.get_category_meta(_m_category)
                            _meta_data = _meta_result.get("data", {})
                            st.session_state[_meta_cache_key] = _meta_data
                        except Exception as e:
                            st.error(f"메타정보 조회 실패: {e}")

                    _cached_meta = st.session_state.get(_meta_cache_key)
                    if _cached_meta:
                        _meta_c1, _meta_c2 = st.columns(2)
                        with _meta_c1:
                            st.markdown("**필수 고시정보**")
                            for _nc in _cached_meta.get("noticeCategories", []):
                                st.markdown(f"*{_nc.get('noticeCategoryName', '')}*")
                                for _nd in _nc.get("noticeCategoryDetailNames", []):
                                    _req_mark = " 🔴" if _nd.get("required") == "MANDATORY" else ""
                                    st.caption(f"  - {_nd.get('noticeCategoryDetailName', '')}{_req_mark}")
                        with _meta_c2:
                            st.markdown("**필수 속성 (구매옵션)**")
                            for _attr in _cached_meta.get("attributes", []):
                                _req = _attr.get("required", "")
                                _exposed = _attr.get("exposed", "")
                                _icon = "🔴" if _req == "MANDATORY" else ("🟡" if _exposed == "EXPOSED" else "⚪")
                                st.caption(f"{_icon} {_attr.get('attributeTypeName', '')} ({_attr.get('dataType', '')}) — {_req}")

                        # 인증 정보
                        _certs = _cached_meta.get("certifications", [])
                        _mandatory_certs = [c for c in _certs if c.get("required") in ("MANDATORY", "RECOMMEND")]
                        if _mandatory_certs:
                            st.markdown("**인증 정보**")
                            for _cert in _mandatory_certs:
                                _cert_req = "필수" if _cert.get("required") == "MANDATORY" else "추천"
                                st.caption(f"- {_cert.get('name', '')} ({_cert_req})")

                        # 허용 상품 상태
                        _allowed = _cached_meta.get("allowedOfferConditions", [])
                        if _allowed:
                            st.caption(f"허용 상품상태: {', '.join(_allowed)}")
                else:
                    st.caption("WING API 계정이 없습니다")

    # ══════════════════════════════════════
    # 섹션 2: 기본 정보 (ISBN 조회 통합)
    # ══════════════════════════════════════
    with st.container(border=True):
        _section_header(2, "기본 정보")

        # ISBN 조회 영역
        isbn_col1, isbn_col2 = st.columns([3, 1])
        with isbn_col1:
            _isbn_input = st.text_input(
                "ISBN 조회", placeholder="978xxxxxxxxxx 입력 후 조회 버튼",
                key="manual_isbn_input", help="ISBN을 입력하면 DB/알라딘에서 자동으로 정보를 채웁니다",
            )
        with isbn_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            _isbn_btn = st.button("조회", key="btn_isbn_lookup", type="primary")

        if _isbn_btn and _isbn_input:
            _isbn_input = _isbn_input.strip()
            _db_book = query_df(
                "SELECT title, author, publisher_name, list_price, image_url, description FROM books WHERE isbn = :isbn LIMIT 1",
                {"isbn": _isbn_input}
            )
            if not _db_book.empty:
                _row = _db_book.iloc[0]
                st.session_state["m_title"] = _row["title"] or ""
                st.session_state["m_author"] = _row["author"] or ""
                st.session_state["m_publisher"] = _row["publisher_name"] or ""
                st.session_state["m_list_price"] = int(_row["list_price"]) if pd.notna(_row["list_price"]) else 0
                st.session_state["m_image"] = _row["image_url"] or ""
                st.session_state["m_desc"] = _row["description"] or ""
                st.session_state["m_isbn"] = _isbn_input
                st.success(f"DB에서 찾음: {_row['title']}")
            else:
                try:
                    _ttb_key = os.getenv("ALADIN_TTB_KEY", "")
                    if not _ttb_key:
                        st.error("ALADIN_TTB_KEY 환경변수가 설정되지 않았습니다.")
                    else:
                        from crawlers.aladin_api_crawler import AladinAPICrawler
                        _crawler = AladinAPICrawler(ttb_key=_ttb_key)
                        _result = _crawler.search_by_isbn(_isbn_input)
                        if _result:
                            st.session_state["m_title"] = _result.get("title", "")
                            st.session_state["m_author"] = _result.get("author", "")
                            st.session_state["m_publisher"] = _result.get("publisher", "")
                            st.session_state["m_list_price"] = _result.get("original_price", 0)
                            st.session_state["m_image"] = _result.get("image_url", "")
                            st.session_state["m_desc"] = _result.get("description", "")
                            st.session_state["m_isbn"] = _isbn_input
                            st.success(f"알라딘에서 찾음: {_result['title']}")
                        else:
                            st.warning(f"ISBN {_isbn_input}을 찾을 수 없습니다. 직접 입력하세요.")
                except Exception as e:
                    st.error(f"알라딘 조회 오류: {e}")

        st.markdown("---")

        # 기본 정보 입력 필드
        _m_col1, _m_col2 = st.columns(2)
        with _m_col1:
            _m_title = st.text_input(
                "상품명 *", value=st.session_state.get("m_title", ""),
                key="m_form_title", help="쿠팡에 표시될 상품명",
            )
            _m_author = st.text_input(
                "저자", value=st.session_state.get("m_author", ""),
                key="m_form_author", help="도서 저자 (상품고시정보에 포함)",
            )
        with _m_col2:
            _m_isbn = st.text_input(
                "ISBN *", value=st.session_state.get("m_isbn", ""),
                key="m_form_isbn", help="13자리 국제 표준 도서 번호",
            )
            _m_publisher = st.text_input(
                "출판사", value=st.session_state.get("m_publisher", ""),
                key="m_form_publisher", help="도서 출판사명",
            )

    # ══════════════════════════════════════
    # 섹션 3: 판매 정보 + 마진 미리보기
    # ══════════════════════════════════════
    with st.container(border=True):
        _section_header(3, "판매 정보")

        _p_col1, _p_col2, _p_col3, _p_col4 = st.columns(4)
        with _p_col1:
            _m_list_price = st.number_input(
                "정가 *", value=st.session_state.get("m_list_price", 0),
                step=1000, min_value=0, key="m_form_list_price",
                help="도서 정가 (표지 가격)",
            )
        with _p_col2:
            _default_sale = int(_m_list_price * 0.9) if _m_list_price > 0 else 0
            _m_sale_price = st.number_input(
                "판매가 *", value=_default_sale, step=100, min_value=0,
                key="m_form_sale_price", help="쿠팡 실제 판매가",
            )
        with _p_col3:
            _m_tax = st.selectbox(
                "과세유형", ["비과세 (도서)", "과세"], index=0,
                key="m_form_tax", help="도서는 기본 비과세",
            )
        with _p_col4:
            _m_shipping = st.radio(
                "배송비", ["무료배송", "유료(2,500원)"],
                index=0, key="m_form_shipping", horizontal=True,
            )

        # 마진 미리보기
        if _m_sale_price > 0 and _m_list_price > 0:
            _commission_rate = 0.11
            _commission = int(_m_sale_price * _commission_rate)
            _shipping_cost = 2300
            _margin = _m_sale_price - _m_list_price - _commission - _shipping_cost
            _margin_rate = (_margin / _m_sale_price * 100) if _m_sale_price > 0 else 0
            _margin_color = "#2E7D32" if _margin >= 0 else "#D32F2F"

            st.markdown("---")
            _mg1, _mg2, _mg3, _mg4 = st.columns(4)
            with _mg1:
                st.metric("쿠팡 수수료 (11%)", f"₩{_commission:,}")
            with _mg2:
                st.metric("배송 원가", f"₩{_shipping_cost:,}")
            with _mg3:
                st.metric("예상 순마진", f"₩{_margin:,}", delta=f"{_margin_rate:+.1f}%")
            with _mg4:
                _discount_rate = round((1 - _m_sale_price / _m_list_price) * 100, 1) if _m_list_price > 0 else 0
                st.metric("할인율", f"{_discount_rate}%")

            if _margin < 0:
                st.warning(f"마진이 적자입니다 (₩{_margin:,}). 판매가를 조정하세요.")

    # ══════════════════════════════════════
    # 섹션 4: 이미지 / 상세 + 자동생성 필드
    # ══════════════════════════════════════
    with st.container(border=True):
        _section_header(4, "이미지 / 상세 정보")

        _img_col, _desc_col = st.columns([1, 2])
        with _img_col:
            _m_image = st.text_input(
                "대표이미지 URL", value=st.session_state.get("m_image", ""),
                key="m_form_image", help="500x500 이상 권장",
            )
            if _m_image:
                try:
                    st.image(_m_image, width=200)
                except Exception:
                    st.caption("이미지를 불러올 수 없습니다")
        with _desc_col:
            _m_desc = st.text_area(
                "상품 설명", value=st.session_state.get("m_desc", ""),
                height=150, key="m_form_desc", help="HTML 태그 사용 가능",
            )

        st.markdown("---")
        st.markdown("**자동생성 필드 미리보기** — 등록 시 아래 정보가 자동으로 포함됩니다")

        _prev_col1, _prev_col2 = st.columns(2)

        # 상품고시정보 (API 메타 우선, 없으면 하드코딩 fallback)
        _meta_cache_key = f"_cat_meta_{_m_category}"
        _cached_meta = st.session_state.get(_meta_cache_key)
        with _prev_col1:
            _notice_label = "상품고시정보"
            if _cached_meta and _cached_meta.get("noticeCategories"):
                _notice_label = f"상품고시정보 ({_cached_meta['noticeCategories'][0].get('noticeCategoryName', '')})"
            with st.expander(_notice_label, expanded=False):
                if _cached_meta and _cached_meta.get("noticeCategories"):
                    for _nc in _cached_meta["noticeCategories"]:
                        st.caption(f"{_nc.get('noticeCategoryName', '')}")
                        for _nd in _nc.get("noticeCategoryDetailNames", []):
                            _req_icon = "🔴" if _nd.get("required") == "MANDATORY" else "⚪"
                            st.markdown(f"- {_req_icon} **{_nd.get('noticeCategoryDetailName', '')}**")
                elif _m_title:
                    st.caption("서적 기본값 (섹션1 메타정보 조회 시 API 데이터로 교체)")
                    _notices = _build_book_notices(_m_title, _m_author or "", _m_publisher or "")
                    for _n in _notices:
                        st.markdown(f"- **{_n.get('noticeCategoryDetailName', '')}**: {_n.get('content', '')}")
                else:
                    st.caption("상품명을 입력하면 미리보기가 표시됩니다")

        # 필수 속성 (API 메타 우선, 없으면 하드코딩 fallback)
        with _prev_col2:
            with st.expander("필수 속성 (구매옵션)", expanded=False):
                if _cached_meta and _cached_meta.get("attributes"):
                    _mandatory_attrs = [a for a in _cached_meta["attributes"] if a.get("required") == "MANDATORY"]
                    _optional_attrs = [a for a in _cached_meta["attributes"] if a.get("required") != "MANDATORY" and a.get("exposed") == "EXPOSED"]
                    if _mandatory_attrs:
                        st.caption("필수:")
                        for _a in _mandatory_attrs:
                            _unit = f" ({_a.get('basicUnit', '')})" if _a.get("basicUnit", "없음") != "없음" else ""
                            st.markdown(f"- 🔴 **{_a.get('attributeTypeName', '')}** [{_a.get('dataType', '')}]{_unit}")
                    if _optional_attrs:
                        st.caption("선택 (구매옵션):")
                        for _a in _optional_attrs[:5]:
                            st.markdown(f"- ⚪ {_a.get('attributeTypeName', '')} [{_a.get('dataType', '')}]")
                        if len(_optional_attrs) > 5:
                            st.caption(f"... 외 {len(_optional_attrs) - 5}개")
                elif _m_isbn:
                    st.caption("도서 기본값 (섹션1 메타정보 조회 시 API 데이터로 교체)")
                    _attrs = _build_book_attributes(_m_isbn, _m_publisher or "", _m_author or "")
                    for _a in _attrs:
                        st.markdown(f"- **{_a.get('attributeTypeName', '')}**: {_a.get('attributeValueName', '')}")
                else:
                    st.caption("ISBN을 입력하면 미리보기가 표시됩니다")

        # 검색 태그
        with st.expander("검색 태그 (최대 20개)", expanded=True):
            if _m_title:
                _product_data_for_tags = {
                    "product_name": _m_title,
                    "publisher": _m_publisher or "",
                    "author": _m_author or "",
                    "isbn": _m_isbn or "",
                }
                # 태그 생성을 위해 임시 WING 클라이언트 사용
                _wing_accs_tag = accounts_df[(accounts_df["wing_api_enabled"] == 1)].to_dict("records")
                _tags = []
                if _wing_accs_tag:
                    _tag_client = create_wing_client(_wing_accs_tag[0])
                    if _tag_client:
                        _tag_uploader = CoupangAPIUploader(_tag_client)
                        try:
                            _tags = _tag_uploader._generate_search_tags(_product_data_for_tags)
                        except Exception:
                            _tags = []
                if _tags:
                    _pills_html = " ".join([f'<span class="tag-pill">{t}</span>' for t in _tags])
                    st.markdown(f"총 **{len(_tags)}**개 태그: {_pills_html}", unsafe_allow_html=True)
                else:
                    st.caption("태그를 생성할 수 없습니다 (WING API 계정 필요)")
            else:
                st.caption("상품명을 입력하면 검색 태그 미리보기가 표시됩니다")

    # ══════════════════════════════════════
    # 섹션 5: 등록 계정 + 검토
    # ══════════════════════════════════════
    with st.container(border=True):
        _section_header(5, "등록 계정 선택 및 검토")

        _wing_accounts = accounts_df[accounts_df["wing_api_enabled"] == 1].to_dict("records")

        if not _wing_accounts:
            st.warning("WING API가 활성화된 계정이 없습니다.")
            st.stop()

        # 자동매칭 동의 상태 조회
        if "_auto_cat_agreed" not in st.session_state:
            st.session_state["_auto_cat_agreed"] = {}
        if st.button("자동매칭 동의 확인", key="btn_check_auto_cat", type="secondary"):
            for _acc in _wing_accounts:
                _chk_client = create_wing_client(_acc)
                if _chk_client:
                    try:
                        _chk_result = _chk_client.check_auto_category_agreed()
                        st.session_state["_auto_cat_agreed"][_acc["account_name"]] = _chk_result.get("data", False)
                    except Exception:
                        st.session_state["_auto_cat_agreed"][_acc["account_name"]] = None

        # 계정 선택 테이블 (data_editor)
        _acc_table_data = []
        for _acc in _wing_accounts:
            _agreed_val = st.session_state.get("_auto_cat_agreed", {}).get(_acc["account_name"])
            _agreed_str = "O" if _agreed_val is True else ("X" if _agreed_val is False else "-")
            _acc_table_data.append({
                "선택": True,
                "계정명": _acc["account_name"],
                "vendorId": _acc.get("vendor_id", ""),
                "출고지": _acc.get("outbound_shipping_code", "-"),
                "반품센터": _acc.get("return_center_code", "-"),
                "자동매칭": _agreed_str,
            })
        _acc_df = pd.DataFrame(_acc_table_data)
        _edited_acc = st.data_editor(
            _acc_df, hide_index=True, key="m_acc_editor",
            column_config={
                "선택": st.column_config.CheckboxColumn("선택", default=True),
                "계정명": st.column_config.TextColumn("계정명", disabled=True),
                "vendorId": st.column_config.TextColumn("Vendor ID", disabled=True),
                "출고지": st.column_config.TextColumn("출고지 코드", disabled=True),
                "반품센터": st.column_config.TextColumn("반품센터 코드", disabled=True),
                "자동매칭": st.column_config.TextColumn("자동매칭", disabled=True, help="카테고리 자동매칭 서비스 동의 여부"),
            },
            width="stretch",
        )

        # 선택된 계정 추출
        _selected_accounts = []
        for _idx, _erow in _edited_acc.iterrows():
            if _erow["선택"]:
                # 원본 dict에서 해당 계정 찾기
                for _acc in _wing_accounts:
                    if _acc["account_name"] == _erow["계정명"]:
                        _selected_accounts.append(_acc)
                        break

        _sel_count = len(_selected_accounts)
        st.caption(f"**{_sel_count}**개 계정 선택됨 / 전체 {len(_wing_accounts)}개")

        st.markdown("---")

        # 검증 요약
        _shipping_policy = "free" if _m_shipping == "무료배송" else "paid"
        _checks = {
            "상품명": bool(_m_title),
            "ISBN": bool(_m_isbn),
            "정가 > 0": _m_list_price > 0,
            "판매가 > 0": _m_sale_price > 0,
            "등록 계정": _sel_count > 0,
        }
        _all_pass = all(_checks.values())

        _check_items = []
        for _label, _ok in _checks.items():
            if _ok:
                _check_items.append(f'<span class="check-ok">&#10004; {_label}</span>')
            else:
                _check_items.append(f'<span class="check-fail">&#10008; {_label}</span>')
        st.markdown("**등록 전 검증:** " + " &nbsp;|&nbsp; ".join(_check_items), unsafe_allow_html=True)

        if _all_pass:
            st.success("모든 필수 항목이 충족되었습니다. 등록할 수 있습니다.")
        else:
            _missing = [k for k, v in _checks.items() if not v]
            st.warning(f"미충족 항목: {', '.join(_missing)}")

        # 페이로드 미리보기
        _product_data = {
            "product_name": _m_title,
            "publisher": _m_publisher,
            "author": _m_author,
            "isbn": _m_isbn,
            "original_price": _m_list_price,
            "sale_price": _m_sale_price,
            "main_image_url": _m_image,
            "description": _m_desc or "상세페이지 참조",
            "shipping_policy": _shipping_policy,
        }

        with st.expander("페이로드 미리보기"):
            if _selected_accounts and _m_title:
                _preview_acc = _selected_accounts[0]
                _preview_client = create_wing_client(_preview_acc)
                if _preview_client:
                    _preview_uploader = CoupangAPIUploader(_preview_client, vendor_user_id=_preview_acc["account_name"])
                    try:
                        _preview_payload = _preview_uploader.build_product_payload(
                            _product_data,
                            str(_preview_acc.get("outbound_shipping_code", "")),
                            str(_preview_acc.get("return_center_code", "")),
                            category_code=_m_category if _m_category else None,
                        )
                        import json as _json
                        st.code(_json.dumps(_preview_payload, indent=2, ensure_ascii=False), language="json")
                    except Exception as e:
                        st.error(f"페이로드 생성 오류: {e}")
                else:
                    st.warning("WING API 클라이언트 생성 실패")
            else:
                st.info("상품명을 입력하고 계정을 선택하면 페이로드를 미리 볼 수 있습니다.")

        st.markdown("---")

        # 등록 실행 버튼
        _can_register = _all_pass
        _btn_register = st.button(
            f"등록하기 ({_sel_count}개 계정)",
            type="primary",
            disabled=not _can_register,
            key="btn_manual_register",
        )

        if _btn_register and _can_register:
            _reg_progress = st.progress(0, text="등록 준비 중...")
            _reg_results = st.container()
            _ok_list, _fail_list = [], []

            for _i, _acc in enumerate(_selected_accounts):
                _acc_name = _acc["account_name"]
                _reg_progress.progress((_i + 1) / len(_selected_accounts), text=f"[{_i+1}/{len(_selected_accounts)}] {_acc_name} 등록 중...")

                _out_code = str(_acc.get("outbound_shipping_code", ""))
                _ret_code = str(_acc.get("return_center_code", ""))

                if not _out_code or not _ret_code:
                    _fail_list.append({"계정": _acc_name, "결과": "출고지/반품지 코드 미설정"})
                    continue

                _client = create_wing_client(_acc)
                if _client is None:
                    _fail_list.append({"계정": _acc_name, "결과": "API 키 미설정"})
                    continue

                _uploader = CoupangAPIUploader(_client, vendor_user_id=_acc_name)
                try:
                    _res = _uploader.upload_product(
                        _product_data, _out_code, _ret_code,
                    )
                    if _res["success"]:
                        _sid = _res["seller_product_id"]
                        _ok_list.append({"계정": _acc_name, "쿠팡ID": _sid, "결과": "성공"})
                        try:
                            with engine.connect() as conn:
                                conn.execute(text("""
                                    INSERT OR IGNORE INTO listings
                                    (account_id, product_type, isbn, coupang_product_id,
                                     coupang_status, sale_price, original_price, product_name,
                                     shipping_policy, upload_method, uploaded_at)
                                    VALUES (:aid, 'single', :isbn, :cid, 'active', :sp, :op, :pn, :ship, 'api', :now)
                                """), {
                                    "aid": int(_acc["id"]),
                                    "isbn": _m_isbn,
                                    "cid": _sid,
                                    "sp": _m_sale_price,
                                    "op": _m_list_price,
                                    "pn": _m_title,
                                    "ship": _shipping_policy,
                                    "now": datetime.now().isoformat(),
                                })
                                conn.commit()
                        except Exception as _db_e:
                            logger.warning(f"DB 저장 실패 ({_acc_name}): {_db_e}")
                    else:
                        _fail_list.append({"계정": _acc_name, "결과": _res["message"][:120]})
                except Exception as _e:
                    _fail_list.append({"계정": _acc_name, "결과": str(_e)[:120]})

            _reg_progress.progress(1.0, text="완료!")
            with _reg_results:
                if _ok_list:
                    st.success(f"성공: {len(_ok_list)}건")
                    st.dataframe(pd.DataFrame(_ok_list), width="stretch", hide_index=True)
                if _fail_list:
                    st.error(f"실패: {len(_fail_list)}건")
                    st.dataframe(pd.DataFrame(_fail_list), width="stretch", hide_index=True)
            query_df.clear()


# ═══════════════════════════════════════
# 매출
# ═══════════════════════════════════════
elif page == "매출":
    st.title("매출 분석")

    def _fmt_krw(val):
        """한국식 금액 표시 (₩520만, ₩1.2억)"""
        val = int(val)
        if abs(val) >= 100_000_000:
            return f"₩{val / 100_000_000:.1f}억"
        elif abs(val) >= 10_000:
            return f"₩{val / 10_000:.0f}만"
        else:
            return f"₩{val:,}"

    # ── 상단 컨트롤 ──
    ctrl1, ctrl2, ctrl3 = st.columns([3, 3, 2])
    with ctrl1:
        period_opt = st.selectbox("기간", ["1주", "1개월", "3개월"], index=2, key="rev_period")
    with ctrl2:
        account_filter = st.selectbox("계정", ["전체"] + account_names, key="rev_acct")
    with ctrl3:
        st.markdown("<br>", unsafe_allow_html=True)
        btn_sync = st.button("매출 동기화", type="primary", key="btn_rev_sync", width="stretch")

    # 기간 계산
    period_map = {"1주": 7, "1개월": 30, "3개월": 90}
    days_back = period_map[period_opt]
    from datetime import date as _date, timedelta as _td
    date_to = _date.today()
    date_from = date_to - _td(days=days_back)
    date_from_str = date_from.isoformat()
    date_to_str = date_to.isoformat()
    prev_date_to = date_from - _td(days=1)
    prev_date_from = prev_date_to - _td(days=days_back)
    prev_from_str = prev_date_from.isoformat()
    prev_to_str = prev_date_to.isoformat()

    # revenue_history 테이블 보장
    with engine.connect() as _conn:
        _conn.execute(text("""
            CREATE TABLE IF NOT EXISTS revenue_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                order_id BIGINT NOT NULL,
                sale_type VARCHAR(10) NOT NULL,
                sale_date DATE NOT NULL,
                recognition_date DATE NOT NULL,
                settlement_date DATE,
                product_id BIGINT,
                product_name VARCHAR(500),
                vendor_item_id BIGINT,
                vendor_item_name VARCHAR(500),
                sale_price INTEGER DEFAULT 0,
                quantity INTEGER DEFAULT 0,
                coupang_discount INTEGER DEFAULT 0,
                sale_amount INTEGER DEFAULT 0,
                seller_discount INTEGER DEFAULT 0,
                service_fee INTEGER DEFAULT 0,
                service_fee_vat INTEGER DEFAULT 0,
                service_fee_ratio REAL,
                settlement_amount INTEGER DEFAULT 0,
                delivery_fee_amount INTEGER DEFAULT 0,
                delivery_fee_settlement INTEGER DEFAULT 0,
                listing_id INTEGER REFERENCES listings(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, order_id, vendor_item_id)
            )
        """))
        _conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rev_account_date ON revenue_history(account_id, recognition_date)"))
        _conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rev_recognition ON revenue_history(recognition_date)"))
        _conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rev_listing ON revenue_history(listing_id)"))
        _conn.commit()

    # 동기화 실행
    if btn_sync:
        try:
            from scripts.sync_revenue import RevenueSync
            months = {7: 1, 30: 1, 90: 3}[days_back]
            syncer = RevenueSync(db_path=str(DB_PATH))
            acct_arg = None if account_filter == "전체" else account_filter
            sync_progress = st.progress(0, text="매출 동기화 중...")
            results = syncer.sync_all(
                months=months, account_name=acct_arg,
                progress_callback=lambda cur, tot, msg: sync_progress.progress(
                    min(cur / max(tot, 1), 1.0), text=msg),
            )
            sync_progress.progress(1.0, text="완료!")
            total_i = sum(r["inserted"] for r in results)
            total_f = sum(r["fetched"] for r in results)
            st.success(f"동기화 완료: {len(results)}개 계정, 조회 {total_f:,}건, 신규 저장 {total_i:,}건")
            query_df.clear()
        except Exception as e:
            st.error(f"동기화 오류: {e}")
            logger.exception("매출 동기화 오류")

    st.divider()

    # ── 계정 필터 조건 ──
    acct_where = ""
    _acct_id = None
    if account_filter != "전체":
        _aid_row = query_df("SELECT id FROM accounts WHERE account_name = :name LIMIT 1", {"name": account_filter})
        if _aid_row.empty:
            st.error(f"계정 '{account_filter}'을 찾을 수 없습니다.")
            st.stop()
        _acct_id = int(_aid_row.iloc[0]["id"])
        acct_where = f"AND r.account_id = {_acct_id}"

    # ── KPI 조회 (현재 + 전기) ──
    _kpi_tpl = """
        SELECT
            COALESCE(SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END), 0) as revenue,
            COALESCE(SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END), 0) as settlement,
            COALESCE(SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END), 0) as orders,
            COALESCE(SUM(CASE WHEN r.sale_type='REFUND' THEN r.quantity ELSE 0 END), 0) as refunds
        FROM revenue_history r
        WHERE r.recognition_date BETWEEN '{d_from}' AND '{d_to}' {aw}
    """
    kpi_cur = query_df(_kpi_tpl.format(d_from=date_from_str, d_to=date_to_str, aw=acct_where))
    kpi_prev = query_df(_kpi_tpl.format(d_from=prev_from_str, d_to=prev_to_str, aw=acct_where))

    kc = kpi_cur.iloc[0] if not kpi_cur.empty else None
    kp = kpi_prev.iloc[0] if not kpi_prev.empty else None

    if kc is None or (int(kc["revenue"]) == 0 and int(kc["orders"]) == 0):
        st.info("해당 기간 매출 데이터가 없습니다. '매출 동기화' 버튼을 눌러주세요.")
        st.stop()

    cur_rev = int(kc["revenue"])
    cur_settle = int(kc["settlement"])
    cur_orders = int(kc["orders"])
    cur_refunds = int(kc["refunds"])
    prev_rev = int(kp["revenue"]) if kp is not None else 0
    prev_settle = int(kp["settlement"]) if kp is not None else 0
    prev_orders = int(kp["orders"]) if kp is not None else 0

    # ── KPI 카드 (5개 + 전기대비) ──
    def _delta(cur, prev):
        if prev == 0:
            return None
        pct = round((cur - prev) / prev * 100)
        return f"{'+' if pct > 0 else ''}{pct}%"

    cur_avg_price = round(cur_rev / cur_orders) if cur_orders > 0 else 0
    prev_avg_price = round(prev_rev / prev_orders) if prev_orders > 0 else 0
    cur_refund_rate = round(cur_refunds / (cur_orders + cur_refunds) * 100, 1) if (cur_orders + cur_refunds) > 0 else 0
    prev_refunds = int(kp["refunds"]) if kp is not None else 0
    prev_refund_rate = round(prev_refunds / (prev_orders + prev_refunds) * 100, 1) if (prev_orders + prev_refunds) > 0 else 0

    kc1, kc2, kc3, kc4, kc5 = st.columns(5)
    kc1.metric("총 매출", _fmt_krw(cur_rev), delta=_delta(cur_rev, prev_rev))
    kc2.metric("정산금액", _fmt_krw(cur_settle), delta=_delta(cur_settle, prev_settle))
    kc3.metric("주문 수", f"{cur_orders:,}건", delta=_delta(cur_orders, prev_orders))
    kc4.metric("평균 단가", _fmt_krw(cur_avg_price), delta=_delta(cur_avg_price, prev_avg_price))
    kc5.metric("환불률", f"{cur_refund_rate}%", delta=_delta(cur_refund_rate, prev_refund_rate) if prev_refund_rate > 0 else None, delta_color="inverse")

    st.caption(f"{date_from_str} ~ {date_to_str}  |  비교: {prev_from_str} ~ {prev_to_str}")

    # ── 인사이트 요약 ──
    _insights = []

    # 매출 증감
    if prev_rev > 0:
        _rev_pct = round((cur_rev - prev_rev) / prev_rev * 100)
        _diff = _fmt_krw(abs(cur_rev - prev_rev))
        if _rev_pct > 5:
            _insights.append(f"매출이 전기 대비 **{_rev_pct}% 상승** ({_diff} 증가)")
        elif _rev_pct < -5:
            _insights.append(f"매출이 전기 대비 **{abs(_rev_pct)}% 하락** ({_diff} 감소)")
        else:
            _insights.append("전기 대비 매출 **비슷한 수준** 유지")

    # 베스트셀러
    _best1 = query_df(f"""
        SELECT r.product_name, SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as qty
        FROM revenue_history r
        WHERE r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}' {acct_where}
        GROUP BY r.vendor_item_id ORDER BY qty DESC LIMIT 1
    """)
    if not _best1.empty and int(_best1.iloc[0]["qty"]) > 0:
        _b = _best1.iloc[0]
        _bname = str(_b["product_name"])[:30]
        _insights.append(f"베스트셀러: **{_bname}** ({int(_b['qty'])}건)")

    # 최고 매출 계정 (전체일 때)
    if account_filter == "전체":
        _top_acct = query_df(f"""
            SELECT a.account_name,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE 0 END) as rev
            FROM revenue_history r JOIN accounts a ON r.account_id = a.id
            WHERE r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
            GROUP BY r.account_id ORDER BY rev DESC LIMIT 1
        """)
        if not _top_acct.empty and cur_rev > 0:
            _ta = _top_acct.iloc[0]
            _ta_pct = round(int(_ta["rev"]) / cur_rev * 100)
            _insights.append(f"최고 매출: **{_ta['account_name']}** (전체의 {_ta_pct}%)")

    # 환불 경고
    _refund_rate = round(cur_refunds / (cur_orders + cur_refunds) * 100, 1) if (cur_orders + cur_refunds) > 0 else 0
    if _refund_rate > 5:
        _insights.append(f"환불률 **{_refund_rate}%** — 환불 상품 확인 필요")
    elif cur_refunds > 0:
        _insights.append(f"환불 {cur_refunds}건 (환불률 {_refund_rate}%)")

    if _insights:
        st.markdown("**💡 주요 인사이트**")
        for _ins in _insights:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;• {_ins}")

    st.divider()

    # ── 일별 매출 추이 ──
    daily = query_df(f"""
        SELECT r.recognition_date as 날짜,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as 매출,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as 주문수
        FROM revenue_history r
        WHERE r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}' {acct_where}
        GROUP BY r.recognition_date ORDER BY r.recognition_date
    """)
    if not daily.empty:
        daily["날짜"] = pd.to_datetime(daily["날짜"])
        st.line_chart(daily.set_index("날짜")["매출"], width="stretch")

    # ── 하단 탭 ──
    if account_filter == "전체":
        tab_best, tab_compare = st.tabs(["🏆 베스트셀러", "📊 계정 비교"])
    else:
        tab_best, tab_compare = st.tabs(["🏆 베스트셀러", "📦 상세 분석"])

    with tab_best:
        best = query_df(f"""
            SELECT
                r.product_name as 상품명,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as 주문수,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as 매출,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END) as 정산
            FROM revenue_history r
            WHERE r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}' {acct_where}
            GROUP BY r.vendor_item_id ORDER BY 주문수 DESC LIMIT 15
        """)
        if not best.empty:
            best.insert(0, "#", range(1, len(best) + 1))
            st.dataframe(fmt_money_df(best), width="stretch", hide_index=True)
            _csv_best = best.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 베스트셀러 CSV", _csv_best, f"bestseller_{date_from_str}.csv", "text/csv", key="dl_best")
        else:
            st.info("베스트셀러 데이터가 없습니다.")

        with st.expander("💰 광고 추천 (정산율 높은 상품)"):
            st.caption("정산율 높고 주문 2건 이상 = 광고 시 수익 기대")
            ad = query_df(f"""
                SELECT
                    r.product_name as 상품명,
                    SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as 주문수,
                    SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE 0 END) as 정산,
                    ROUND(
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE 0 END) * 100.0 /
                        NULLIF(SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE 0 END), 0), 1
                    ) as '정산율(%)'
                FROM revenue_history r
                WHERE r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}' {acct_where}
                GROUP BY r.vendor_item_id
                HAVING 주문수 >= 2
                ORDER BY SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE 0 END) * 1.0 /
                         NULLIF(SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE 0 END), 0) DESC
                LIMIT 10
            """)
            if not ad.empty:
                st.dataframe(fmt_money_df(ad), width="stretch", hide_index=True)
            else:
                st.info("주문 2건 이상인 상품이 없습니다.")

    with tab_compare:
        if account_filter == "전체":
            # 계정별 매출 비교
            acct_rev = query_df(f"""
                SELECT a.account_name as 계정,
                    SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as 매출,
                    SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as 주문수,
                    SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END) as 정산,
                    ROUND(
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE 0 END) * 100.0 /
                        NULLIF(SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE 0 END), 0), 1
                    ) as '정산율(%)'
                FROM revenue_history r
                JOIN accounts a ON r.account_id = a.id
                WHERE r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
                GROUP BY r.account_id ORDER BY 매출 DESC
            """)
            if not acct_rev.empty:
                _chart_col, _pie_col = st.columns([3, 2])
                with _chart_col:
                    st.bar_chart(acct_rev.set_index("계정")["매출"])
                with _pie_col:
                    import plotly.express as px
                    _pie = acct_rev[acct_rev["매출"] > 0]
                    if not _pie.empty:
                        fig = px.pie(_pie, values="매출", names="계정", title="매출 비중",
                                     hole=0.4, color_discrete_sequence=px.colors.qualitative.Set2)
                        fig.update_layout(margin=dict(t=40, b=10, l=10, r=10), height=300, showlegend=True)
                        st.plotly_chart(fig, width="stretch")
                st.dataframe(fmt_money_df(acct_rev), width="stretch", hide_index=True)
                _csv_acct = acct_rev.to_csv(index=False).encode("utf-8-sig")
                st.download_button("📥 계정 비교 CSV", _csv_acct, f"account_compare_{date_from_str}.csv", "text/csv", key="dl_acct_cmp")
            else:
                st.info("계정별 데이터가 없습니다.")
        else:
            # 계정 상세: 4탭
            _dtab1, _dtab2, _dtab3, _dtab4 = st.tabs(["📦 상품별", "📚 출판사별", "📅 월별 추이", "↩️ 환불"])

            with _dtab1:
                prod_detail = query_df(f"""
                    SELECT
                        r.product_name as 상품명,
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as 주문수,
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as 매출,
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END) as 정산,
                        ROUND(
                            SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE 0 END) * 100.0 /
                            NULLIF(SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE 0 END), 0), 1
                        ) as '정산율(%)'
                    FROM revenue_history r
                    WHERE r.account_id = {_acct_id}
                      AND r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
                    GROUP BY r.vendor_item_id ORDER BY 매출 DESC LIMIT 20
                """)
                if not prod_detail.empty:
                    prod_detail.insert(0, "#", range(1, len(prod_detail) + 1))
                    st.dataframe(fmt_money_df(prod_detail), width="stretch", hide_index=True)
                    # Top 10 bar chart
                    _top10 = prod_detail.head(10).copy()
                    _top10["_label"] = _top10["상품명"].str[:20]
                    st.bar_chart(_top10.set_index("_label")["매출"])
                    # CSV 다운로드
                    _csv_prod = prod_detail.to_csv(index=False).encode("utf-8-sig")
                    st.download_button("📥 상품별 CSV", _csv_prod, f"products_{account_filter}_{date_from_str}.csv", "text/csv", key="dl_prod")
                else:
                    st.info("상품별 데이터가 없습니다.")

            with _dtab2:
                pub_rev = query_df(f"""
                    SELECT
                        COALESCE(b.publisher_name, '(미매칭)') as 출판사,
                        COUNT(DISTINCT r.vendor_item_id) as 상품수,
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as 주문수,
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as 매출,
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END) as 정산
                    FROM revenue_history r
                    LEFT JOIN listings l ON r.listing_id = l.id
                    LEFT JOIN products p ON l.product_id = p.id
                    LEFT JOIN books b ON p.book_id = b.id
                    WHERE r.account_id = {_acct_id}
                      AND r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
                    GROUP BY b.publisher_name ORDER BY 매출 DESC
                """)
                if not pub_rev.empty:
                    st.dataframe(fmt_money_df(pub_rev), width="stretch", hide_index=True)
                    _pub_chart = pub_rev[pub_rev["출판사"] != "(미매칭)"].head(10)
                    if not _pub_chart.empty:
                        st.bar_chart(_pub_chart.set_index("출판사")["매출"])
                else:
                    st.info("출판사별 데이터가 없습니다.")

            with _dtab3:
                monthly = query_df(f"""
                    SELECT
                        strftime('%Y-%m', r.recognition_date) as 월,
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as 매출,
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END) as 정산,
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as 주문수
                    FROM revenue_history r
                    WHERE r.account_id = {_acct_id}
                      AND r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
                    GROUP BY strftime('%Y-%m', r.recognition_date) ORDER BY 월
                """)
                if not monthly.empty:
                    st.bar_chart(monthly.set_index("월")[["매출", "정산"]])
                    # 전월 대비 성장률
                    if len(monthly) >= 2:
                        monthly["매출성장률(%)"] = monthly["매출"].pct_change().mul(100).round(1)
                        monthly["주문성장률(%)"] = monthly["주문수"].pct_change().mul(100).round(1)
                    st.dataframe(fmt_money_df(monthly), width="stretch", hide_index=True)
                else:
                    st.info("월별 데이터가 없습니다.")

            with _dtab4:
                # 환불 KPI
                _ref_kpi = query_df(f"""
                    SELECT
                        COALESCE(SUM(r.quantity), 0) as 환불건수,
                        COALESCE(SUM(r.sale_amount), 0) as 환불금액
                    FROM revenue_history r
                    WHERE r.account_id = {_acct_id}
                      AND r.sale_type = 'REFUND'
                      AND r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
                """)
                _rk = _ref_kpi.iloc[0] if not _ref_kpi.empty else None
                _ref_cnt = int(_rk["환불건수"]) if _rk is not None else 0
                _ref_amt = int(_rk["환불금액"]) if _rk is not None else 0
                _ref_rate = round(_ref_cnt / (cur_orders + _ref_cnt) * 100, 1) if (cur_orders + _ref_cnt) > 0 else 0

                _rc1, _rc2, _rc3 = st.columns(3)
                _rc1.metric("환불 건수", f"{_ref_cnt}건")
                _rc2.metric("환불 금액", _fmt_krw(_ref_amt))
                _rc3.metric("환불률", f"{_ref_rate}%")

                if _ref_cnt > 0:
                    refund_list = query_df(f"""
                        SELECT r.product_name as 상품명,
                            SUM(r.quantity) as 환불수량,
                            SUM(r.sale_amount) as 환불금액
                        FROM revenue_history r
                        WHERE r.account_id = {_acct_id}
                          AND r.sale_type = 'REFUND'
                          AND r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
                        GROUP BY r.vendor_item_id ORDER BY 환불수량 DESC LIMIT 10
                    """)
                    if not refund_list.empty:
                        st.dataframe(fmt_money_df(refund_list), width="stretch", hide_index=True)
                else:
                    st.info("환불 내역이 없습니다.")


# ═══════════════════════════════════════
# 트렌드
# ═══════════════════════════════════════
elif page == "트렌드":
    st.title("트렌드 분석")
    import numpy as np
    import plotly.graph_objects as go
    import plotly.express as px

    # ── 계정 필터 ──
    _t_acct_filter = st.selectbox("계정", ["전체"] + account_names, key="trend_acct")
    _t_acct_where = ""
    if _t_acct_filter != "전체":
        _t_aid_row = query_df("SELECT id FROM accounts WHERE account_name = :name LIMIT 1", {"name": _t_acct_filter})
        if _t_aid_row.empty:
            st.error(f"계정 '{_t_acct_filter}'을 찾을 수 없습니다.")
            st.stop()
        _t_acct_id = int(_t_aid_row.iloc[0]["id"])
        _t_acct_where = f"AND r.account_id = {_t_acct_id}"

    # 현재 월(미완료) 제외 — 월초 데이터로 왜곡 방지
    from datetime import date as _t_date
    _t_cur_month = _t_date.today().strftime("%Y-%m")
    _t_month_filter = f"AND strftime('%Y-%m', r.recognition_date) < '{_t_cur_month}'"

    st.divider()

    # ── 인사이트 요약 (모든 탭 데이터를 미리 집계) ──
    _ins_monthly = query_df(f"""
        SELECT strftime('%Y-%m', r.recognition_date) as month,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as revenue,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as orders
        FROM revenue_history r WHERE 1=1 {_t_acct_where} {_t_month_filter}
        GROUP BY strftime('%Y-%m', r.recognition_date) ORDER BY month
    """)

    if not _ins_monthly.empty and len(_ins_monthly) >= 2:
        _ins_items = []

        def _fmt_krw_t(val):
            val = int(val)
            if abs(val) >= 100_000_000:
                return f"₩{val / 100_000_000:.1f}억"
            elif abs(val) >= 10_000:
                return f"₩{val / 10_000:.0f}만"
            else:
                return f"₩{val:,}"

        # 1) 매출 추세 판단
        _ins_r3 = _ins_monthly["revenue"].tail(3).sum()
        _ins_p3 = _ins_monthly["revenue"].iloc[max(0, len(_ins_monthly)-6):max(0, len(_ins_monthly)-3)].sum()
        if _ins_p3 > 0:
            _ins_growth = round((_ins_r3 - _ins_p3) / _ins_p3 * 100, 1)
            _ins_diff = _fmt_krw_t(abs(_ins_r3 - _ins_p3))
            if _ins_growth > 10:
                _ins_items.append(("up", f"매출 **{_ins_growth}%↑** 성장 중 ({_ins_diff} 증가) — 현재 전략 유지하세요"))
            elif _ins_growth > 0:
                _ins_items.append(("flat", f"매출 소폭 **{_ins_growth}%↑** — 추가 등록으로 성장 가속 필요"))
            elif _ins_growth > -10:
                _ins_items.append(("flat", f"매출 소폭 **{abs(_ins_growth)}%↓** — 가격 재검토 또는 신규 등록 필요"))
            else:
                _ins_items.append(("down", f"매출 **{abs(_ins_growth)}%↓** 하락 중 ({_ins_diff} 감소) — 원인 분석 필요"))

        # 2) 예측 방향
        _ins_x = np.arange(len(_ins_monthly))
        _ins_y = _ins_monthly["revenue"].values.astype(float)
        _ins_coeffs = np.polyfit(_ins_x, _ins_y, 1)
        _ins_slope = _ins_coeffs[0]
        _ins_forecast_3m = max(0, int(np.polyval(_ins_coeffs, len(_ins_monthly) + 2)))
        _ins_last_rev = int(_ins_monthly["revenue"].iloc[-1])
        if _ins_forecast_3m > _ins_last_rev * 1.1:
            _ins_items.append(("up", f"3개월 후 예측 **{_fmt_krw_t(_ins_forecast_3m)}** — 우상향 추세"))
        elif _ins_forecast_3m < _ins_last_rev * 0.9:
            _ins_items.append(("down", f"3개월 후 예측 **{_fmt_krw_t(_ins_forecast_3m)}** — 하락 추세, 대응 필요"))

        # 3) 출판사 집중도/성과 (vendor_item_name에서 출판사 매칭)
        _ins_pub = query_df(f"""
            SELECT COALESCE(p.name, '(미매칭)') as publisher,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE 0 END) as revenue
            FROM revenue_history r
            LEFT JOIN publishers p ON p.is_active = 1 AND r.vendor_item_name LIKE '%' || p.name || '%'
            WHERE 1=1 {_t_acct_where} {_t_month_filter}
            GROUP BY p.name ORDER BY revenue DESC
        """)
        if not _ins_pub.empty:
            _ins_total_pub_rev = _ins_pub["revenue"].sum()
            _ins_top1_pub = _ins_pub.iloc[0]
            _ins_top1_pct = round(int(_ins_top1_pub["revenue"]) / _ins_total_pub_rev * 100) if _ins_total_pub_rev > 0 else 0
            if _ins_top1_pct > 50:
                _ins_items.append(("down", f"**{_ins_top1_pub['publisher']}**에 매출 {_ins_top1_pct}% 편중 — 리스크 분산 필요"))
            elif _ins_top1_pct > 30:
                _ins_items.append(("flat", f"Top 출판사 **{_ins_top1_pub['publisher']}** (매출 {_ins_top1_pct}%) — 다른 출판사 확대 고려"))
            # 하락 출판사
            _ins_all_months = sorted(_ins_monthly["month"].unique())
            _ins_recent_m = _ins_all_months[-3:] if len(_ins_all_months) >= 3 else _ins_all_months
            _ins_pub_recent = query_df(f"""
                SELECT COALESCE(p.name, '(미매칭)') as publisher,
                    SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE 0 END) as revenue
                FROM revenue_history r
                LEFT JOIN publishers p ON p.is_active = 1 AND r.vendor_item_name LIKE '%' || p.name || '%'
                WHERE strftime('%Y-%m', r.recognition_date) IN ({','.join(f"'{m}'" for m in _ins_recent_m)}) {_t_acct_where}
                GROUP BY p.name HAVING revenue > 0
            """)
            _ins_pub_prev_m = _ins_all_months[max(0, len(_ins_all_months)-6):max(0, len(_ins_all_months)-3)]
            if _ins_pub_prev_m:
                _ins_pub_prev = query_df(f"""
                    SELECT COALESCE(p.name, '(미매칭)') as publisher,
                        SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE 0 END) as revenue
                    FROM revenue_history r
                    LEFT JOIN publishers p ON p.is_active = 1 AND r.vendor_item_name LIKE '%' || p.name || '%'
                    WHERE strftime('%Y-%m', r.recognition_date) IN ({','.join(f"'{m}'" for m in _ins_pub_prev_m)}) {_t_acct_where}
                    GROUP BY p.name HAVING revenue > 0
                """)
                if not _ins_pub_recent.empty and not _ins_pub_prev.empty:
                    _ins_pc = _ins_pub_recent.merge(_ins_pub_prev, on="publisher", suffixes=("_r", "_p"), how="inner")
                    _ins_pc["growth"] = (_ins_pc["revenue_r"] - _ins_pc["revenue_p"]) / _ins_pc["revenue_p"] * 100
                    _ins_growing = _ins_pc[_ins_pc["growth"] > 20].sort_values("growth", ascending=False)
                    _ins_declining = _ins_pc[_ins_pc["growth"] < -20].sort_values("growth")
                    if not _ins_growing.empty:
                        _g = _ins_growing.iloc[0]
                        _ins_items.append(("up", f"**{_g['publisher']}** 급성장 (+{round(_g['growth'])}%) — 이 출판사 추가 등록 추천"))
                    if not _ins_declining.empty:
                        _d = _ins_declining.iloc[0]
                        _ins_items.append(("down", f"**{_d['publisher']}** 매출 하락 ({round(_d['growth'])}%) — 가격/상품 점검 필요"))

        # 4) 계정 효율
        if _t_acct_filter == "전체":
            _ins_acct = query_df("""
                SELECT a.account_name, COUNT(l.id) as listings,
                    COALESCE(SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE 0 END), 0) as revenue
                FROM accounts a
                LEFT JOIN listings l ON a.id = l.account_id AND l.coupang_status = 'active'
                LEFT JOIN revenue_history r ON a.id = r.account_id
                WHERE a.is_active = 1
                GROUP BY a.id
            """)
            if not _ins_acct.empty and len(_ins_acct) > 1:
                _ins_acct["효율"] = _ins_acct.apply(lambda r: r["revenue"] / r["listings"] if r["listings"] > 0 else 0, axis=1)
                _ins_best = _ins_acct.sort_values("효율", ascending=False).iloc[0]
                _ins_worst = _ins_acct[_ins_acct["listings"] > 0].sort_values("효율").iloc[0] if (_ins_acct["listings"] > 0).any() else None
                if _ins_worst is not None and _ins_best["account_name"] != _ins_worst["account_name"]:
                    _ins_items.append(("flat", f"상품당 매출 최고 **{_ins_best['account_name']}**, 최저 **{_ins_worst['account_name']}** — 저효율 계정 상품 재배치 고려"))

        # 5) 상품 수명주기
        from datetime import date as _ins_date, timedelta as _ins_td
        _ins_today = _ins_date.today()
        _ins_90d = (_ins_today - _ins_td(days=90)).isoformat()
        _ins_lc = query_df(f"""
            SELECT COUNT(DISTINCT r.vendor_item_id) as total,
                COUNT(DISTINCT CASE WHEN r.recognition_date >= '{_ins_90d}' THEN r.vendor_item_id END) as active_90d
            FROM revenue_history r
            WHERE r.sale_type = 'SALE' {_t_acct_where}
        """)
        if not _ins_lc.empty:
            _ins_total = int(_ins_lc.iloc[0]["total"])
            _ins_active = int(_ins_lc.iloc[0]["active_90d"])
            _ins_dormant = _ins_total - _ins_active
            if _ins_total > 0 and _ins_dormant > 0:
                _ins_dormant_pct = round(_ins_dormant / _ins_total * 100)
                if _ins_dormant_pct > 30:
                    _ins_items.append(("down", f"전체 {_ins_total}개 중 **{_ins_dormant}개({_ins_dormant_pct}%)** 90일간 판매 없음 — 가격 인하 또는 정리 검토"))
                elif _ins_dormant_pct > 10:
                    _ins_items.append(("flat", f"90일간 미판매 상품 **{_ins_dormant}개({_ins_dormant_pct}%)** — 모니터링 필요"))

        # 인사이트 표시
        if _ins_items:
            _icon_map = {"up": "🟢", "flat": "🟡", "down": "🔴"}
            st.markdown("### 핵심 인사이트")
            for _dir, _msg in _ins_items:
                st.markdown(f"&nbsp;&nbsp;{_icon_map[_dir]} {_msg}")
            st.divider()

    ttab_a, ttab_b, ttab_c, ttab_d = st.tabs([
        "📈 월별 추이·예측", "🏆 출판사 성과", "📊 계정 성장", "🔄 상품 수명주기"
    ])

    # ─── 탭 A: 월별 매출 추이 + 이동평균 + 예측선 ───
    with ttab_a:
        _t_monthly = query_df(f"""
            SELECT strftime('%Y-%m', r.recognition_date) as month,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as revenue,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as orders,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END) as settlement
            FROM revenue_history r
            WHERE 1=1 {_t_acct_where} {_t_month_filter}
            GROUP BY strftime('%Y-%m', r.recognition_date) ORDER BY month
        """)

        if _t_monthly.empty or len(_t_monthly) < 2:
            st.info("트렌드 분석에 충분한 월별 데이터가 없습니다. (최소 2개월 필요)")
        else:
            # 이동평균 계산
            _t_monthly["ma3"] = _t_monthly["revenue"].rolling(window=3, min_periods=1).mean().round(0)

            # 예측선 (1차 선형 회귀)
            x = np.arange(len(_t_monthly))
            y = _t_monthly["revenue"].values.astype(float)
            coeffs = np.polyfit(x, y, 1)
            future_x = np.arange(len(x), len(x) + 3)
            forecast = np.polyval(coeffs, future_x)
            forecast = np.maximum(forecast, 0)  # 음수 방지

            # 예측 월 라벨 생성
            last_month = _t_monthly["month"].iloc[-1]
            _lm_y, _lm_m = int(last_month[:4]), int(last_month[5:7])
            _forecast_months = []
            for _fi in range(1, 4):
                _fm = _lm_m + _fi
                _fy = _lm_y
                while _fm > 12:
                    _fm -= 12
                    _fy += 1
                _forecast_months.append(f"{_fy:04d}-{_fm:02d}")

            # KPI: 최근 3개월 vs 이전 3개월
            _recent3 = _t_monthly["revenue"].tail(3).sum()
            _prev3 = _t_monthly["revenue"].iloc[max(0, len(_t_monthly)-6):max(0, len(_t_monthly)-3)].sum()
            _growth_pct = round((_recent3 - _prev3) / _prev3 * 100, 1) if _prev3 > 0 else 0
            _avg_monthly = round(_t_monthly["revenue"].mean())
            _forecast_3m = int(forecast[-1])

            tk1, tk2, tk3 = st.columns(3)
            tk1.metric("최근 3개월 성장률", f"{'+' if _growth_pct > 0 else ''}{_growth_pct}%",
                       delta=f"{'↑' if _growth_pct > 0 else '↓'} vs 이전 3개월")
            tk2.metric("평균 월매출", _fmt_krw_t(_avg_monthly))
            tk3.metric("3개월 후 예측", _fmt_krw_t(_forecast_3m))

            # Plotly 복합 차트
            fig = go.Figure()

            # 매출 bar
            fig.add_trace(go.Bar(
                x=_t_monthly["month"], y=_t_monthly["revenue"],
                name="월매출", marker_color="#636EFA", opacity=0.7,
            ))

            # MA3 line
            fig.add_trace(go.Scatter(
                x=_t_monthly["month"], y=_t_monthly["ma3"],
                name="3개월 이동평균", mode="lines+markers",
                line=dict(color="#EF553B", width=2),
            ))

            # 예측 dashed line
            _forecast_x = [_t_monthly["month"].iloc[-1]] + _forecast_months
            _forecast_y = [float(_t_monthly["revenue"].iloc[-1])] + forecast.tolist()
            fig.add_trace(go.Scatter(
                x=_forecast_x, y=_forecast_y,
                name="예측 (선형)", mode="lines+markers",
                line=dict(color="#00CC96", width=2, dash="dash"),
                marker=dict(symbol="diamond"),
            ))

            fig.update_layout(
                title="월별 매출 추이 + 예측",
                xaxis_title="월", yaxis_title="매출 (원)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(t=60, b=40, l=60, r=20), height=420,
                barmode="overlay",
            )
            st.plotly_chart(fig, width="stretch")

            # 상세 테이블
            with st.expander("월별 상세 데이터"):
                _t_display = _t_monthly.rename(columns={
                    "month": "월", "revenue": "매출", "orders": "주문수",
                    "settlement": "정산", "ma3": "이동평균(3M)"
                })
                st.dataframe(fmt_money_df(_t_display), width="stretch", hide_index=True)

    # ─── 탭 B: 출판사별 성과 랭킹 ───
    with ttab_b:
        _t_pub_monthly = query_df(f"""
            SELECT COALESCE(p.name, '(미매칭)') as publisher,
                strftime('%Y-%m', r.recognition_date) as month,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as revenue,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as orders
            FROM revenue_history r
            LEFT JOIN publishers p ON p.is_active = 1 AND r.vendor_item_name LIKE '%' || p.name || '%'
            WHERE 1=1 {_t_acct_where} {_t_month_filter}
            GROUP BY p.name, strftime('%Y-%m', r.recognition_date) ORDER BY month
        """)

        if _t_pub_monthly.empty:
            st.info("출판사별 데이터가 없습니다.")
        else:
            _all_pub_months = sorted(_t_pub_monthly["month"].unique())
            if len(_all_pub_months) < 2:
                st.info("비교할 수 있는 월별 데이터가 부족합니다. (최소 2개월 필요)")
            else:
                # 최근 3개월 / 이전 3개월 분리
                _recent_3m = _all_pub_months[-3:] if len(_all_pub_months) >= 3 else _all_pub_months
                _prev_3m_end = len(_all_pub_months) - len(_recent_3m)
                _prev_3m = _all_pub_months[max(0, _prev_3m_end - 3):_prev_3m_end]

                _pub_recent = _t_pub_monthly[_t_pub_monthly["month"].isin(_recent_3m)].groupby("publisher").agg(
                    최근매출=("revenue", "sum"), 최근주문=("orders", "sum")).reset_index()
                _pub_prev = _t_pub_monthly[_t_pub_monthly["month"].isin(_prev_3m)].groupby("publisher").agg(
                    이전매출=("revenue", "sum"), 이전주문=("orders", "sum")).reset_index()

                _pub_cmp = _pub_recent.merge(_pub_prev, on="publisher", how="outer").fillna(0)
                _pub_cmp["성장률(%)"] = _pub_cmp.apply(
                    lambda r: round((r["최근매출"] - r["이전매출"]) / r["이전매출"] * 100, 1) if r["이전매출"] > 0 else (100.0 if r["최근매출"] > 0 else 0), axis=1)
                _pub_cmp = _pub_cmp.sort_values("최근매출", ascending=False)

                # Top 10 horizontal bar (성장/하락 색상 구분)
                _top10_pub = _pub_cmp.head(10).copy()
                _top10_pub["color"] = _top10_pub["성장률(%)"].apply(lambda x: "#2ecc71" if x >= 0 else "#e74c3c")

                fig_pub = go.Figure(go.Bar(
                    x=_top10_pub["최근매출"],
                    y=_top10_pub["publisher"],
                    orientation="h",
                    marker_color=_top10_pub["color"],
                    text=_top10_pub["성장률(%)"].apply(lambda x: f"{'+' if x > 0 else ''}{x}%"),
                    textposition="auto",
                ))
                fig_pub.update_layout(
                    title="출판사별 매출 Top 10 (최근 3개월)",
                    xaxis_title="매출 (원)", yaxis_title="",
                    yaxis=dict(autorange="reversed"),
                    margin=dict(t=40, b=40, l=120, r=20), height=400,
                )
                st.plotly_chart(fig_pub, width="stretch")

                # 매출 기여도 pie chart
                _pub_pie_col, _pub_tbl_col = st.columns([2, 3])
                with _pub_pie_col:
                    _pub_pie = _pub_cmp[_pub_cmp["최근매출"] > 0].head(10)
                    if not _pub_pie.empty:
                        fig_pie = px.pie(_pub_pie, values="최근매출", names="publisher",
                                         title="매출 기여도 (최근 3개월)", hole=0.4,
                                         color_discrete_sequence=px.colors.qualitative.Set2)
                        fig_pie.update_layout(margin=dict(t=40, b=10, l=10, r=10), height=350, showlegend=True)
                        st.plotly_chart(fig_pie, width="stretch")

                with _pub_tbl_col:
                    _pub_display = _pub_cmp.rename(columns={"publisher": "출판사"}).head(15)
                    _pub_display["최근매출"] = _pub_display["최근매출"].astype(int)
                    _pub_display["이전매출"] = _pub_display["이전매출"].astype(int)
                    _pub_display["최근주문"] = _pub_display["최근주문"].astype(int)
                    st.dataframe(
                        fmt_money_df(_pub_display[["출판사", "최근매출", "이전매출", "성장률(%)", "최근주문"]]),
                        width="stretch", hide_index=True,
                    )

    # ─── 탭 C: 계정 성장 비교 ───
    with ttab_c:
        _t_acct_monthly = query_df(f"""
            SELECT a.account_name, strftime('%Y-%m', r.recognition_date) as month,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as revenue
            FROM revenue_history r JOIN accounts a ON r.account_id = a.id
            WHERE 1=1 {_t_month_filter}
            GROUP BY a.account_name, strftime('%Y-%m', r.recognition_date) ORDER BY month
        """)

        if _t_acct_monthly.empty:
            st.info("계정별 데이터가 없습니다.")
        else:
            # Multi-line chart (계정별 월매출)
            _acct_pivot = _t_acct_monthly.pivot_table(
                index="month", columns="account_name", values="revenue", fill_value=0
            ).reset_index()

            fig_acct_line = go.Figure()
            _acct_colors = px.colors.qualitative.Set2
            for _ci, _col in enumerate(_acct_pivot.columns[1:]):
                fig_acct_line.add_trace(go.Scatter(
                    x=_acct_pivot["month"], y=_acct_pivot[_col],
                    name=_col, mode="lines+markers",
                    line=dict(color=_acct_colors[_ci % len(_acct_colors)], width=2),
                ))
            fig_acct_line.update_layout(
                title="계정별 월매출 추이",
                xaxis_title="월", yaxis_title="매출 (원)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(t=60, b=40, l=60, r=20), height=400,
            )
            st.plotly_chart(fig_acct_line, width="stretch")

            # 계정별 최근 3개월 성장률
            _acct_months_all = sorted(_t_acct_monthly["month"].unique())
            _acct_recent = _acct_months_all[-3:] if len(_acct_months_all) >= 3 else _acct_months_all
            _acct_prev_end = len(_acct_months_all) - len(_acct_recent)
            _acct_prev = _acct_months_all[max(0, _acct_prev_end - 3):_acct_prev_end]

            _acct_r = _t_acct_monthly[_t_acct_monthly["month"].isin(_acct_recent)].groupby("account_name")["revenue"].sum()
            _acct_p = _t_acct_monthly[_t_acct_monthly["month"].isin(_acct_prev)].groupby("account_name")["revenue"].sum()
            _acct_growth = pd.DataFrame({"최근3M": _acct_r, "이전3M": _acct_p}).fillna(0)
            _acct_growth["성장률(%)"] = _acct_growth.apply(
                lambda r: round((r["최근3M"] - r["이전3M"]) / r["이전3M"] * 100, 1) if r["이전3M"] > 0 else (100.0 if r["최근3M"] > 0 else 0), axis=1)
            _acct_growth = _acct_growth.reset_index().rename(columns={"account_name": "계정"})

            _gc1, _gc2 = st.columns(2)
            with _gc1:
                # 성장률 bar chart
                _ag_colors = _acct_growth["성장률(%)"].apply(lambda x: "#2ecc71" if x >= 0 else "#e74c3c")
                fig_ag = go.Figure(go.Bar(
                    x=_acct_growth["계정"], y=_acct_growth["성장률(%)"],
                    marker_color=_ag_colors,
                    text=_acct_growth["성장률(%)"].apply(lambda x: f"{'+' if x > 0 else ''}{x}%"),
                    textposition="auto",
                ))
                fig_ag.update_layout(
                    title="계정별 성장률 (최근 3M vs 이전 3M)",
                    xaxis_title="", yaxis_title="성장률 (%)",
                    margin=dict(t=40, b=40, l=40, r=20), height=350,
                )
                st.plotly_chart(fig_ag, width="stretch")

            with _gc2:
                # 등록 상품수 vs 매출 scatter
                _acct_listing_cnt = query_df("""
                    SELECT a.account_name as 계정, COUNT(l.id) as 등록상품수
                    FROM accounts a LEFT JOIN listings l ON a.id = l.account_id AND l.coupang_status = 'active'
                    WHERE a.is_active = 1 GROUP BY a.id
                """)
                _acct_total_rev = _t_acct_monthly[_t_acct_monthly["month"].isin(_acct_recent)].groupby("account_name")["revenue"].sum().reset_index()
                _acct_total_rev.columns = ["계정", "최근매출"]
                _scatter = _acct_listing_cnt.merge(_acct_total_rev, on="계정", how="inner")

                if not _scatter.empty:
                    fig_scatter = px.scatter(
                        _scatter, x="등록상품수", y="최근매출", text="계정",
                        title="등록 상품수 vs 매출",
                        color_discrete_sequence=["#636EFA"],
                    )
                    fig_scatter.update_traces(textposition="top center", marker=dict(size=12))
                    fig_scatter.update_layout(
                        margin=dict(t=40, b=40, l=40, r=20), height=350,
                    )
                    st.plotly_chart(fig_scatter, width="stretch")

            # 상세 테이블
            st.dataframe(fmt_money_df(_acct_growth), width="stretch", hide_index=True)

    # ─── 탭 D: 상품 수명주기 분석 ───
    with ttab_d:
        _t_lifecycle = query_df(f"""
            SELECT r.vendor_item_id, r.product_name,
                MIN(r.recognition_date) as first_sale, MAX(r.recognition_date) as last_sale,
                SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as total_orders,
                COUNT(DISTINCT strftime('%Y-%m', r.recognition_date)) as active_months
            FROM revenue_history r
            WHERE r.sale_type = 'SALE' {_t_acct_where}
            GROUP BY r.vendor_item_id HAVING total_orders > 0
        """)

        if _t_lifecycle.empty:
            st.info("상품 수명주기 데이터가 없습니다.")
        else:
            from datetime import date as _lc_date, timedelta as _lc_td
            _today = _lc_date.today()
            _30d_ago = (_today - _lc_td(days=30)).isoformat()
            _90d_ago = (_today - _lc_td(days=90)).isoformat()

            # 최근 3개월 vs 이전 3개월 주문수로 성장/쇠퇴 판단
            _t_recent_orders = query_df(f"""
                SELECT r.vendor_item_id,
                    SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as recent_orders
                FROM revenue_history r
                WHERE r.sale_type = 'SALE' AND r.recognition_date >= '{_90d_ago}' {_t_acct_where}
                GROUP BY r.vendor_item_id
            """)
            _t_prev_orders = query_df(f"""
                SELECT r.vendor_item_id,
                    SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as prev_orders
                FROM revenue_history r
                WHERE r.sale_type = 'SALE'
                    AND r.recognition_date < '{_90d_ago}'
                    AND r.recognition_date >= date('{_90d_ago}', '-90 days') {_t_acct_where}
                GROUP BY r.vendor_item_id
            """)

            _lc = _t_lifecycle.copy()
            _lc = _lc.merge(_t_recent_orders, on="vendor_item_id", how="left")
            _lc["recent_orders"] = pd.to_numeric(_lc["recent_orders"], errors="coerce").fillna(0).astype(int)
            _lc = _lc.merge(_t_prev_orders, on="vendor_item_id", how="left")
            _lc["prev_orders"] = pd.to_numeric(_lc["prev_orders"], errors="coerce").fillna(0).astype(int)

            # 분류
            def _classify(row):
                if row["first_sale"] >= _30d_ago:
                    return "신규"
                elif row["recent_orders"] > row["prev_orders"] and row["recent_orders"] > 0:
                    return "성장"
                elif row["recent_orders"] > 0 and row["recent_orders"] >= row["prev_orders"] * 0.7:
                    return "안정"
                else:
                    return "쇠퇴"

            _lc["분류"] = _lc.apply(_classify, axis=1)

            _new_cnt = len(_lc[_lc["분류"] == "신규"])
            _grow_cnt = len(_lc[_lc["분류"] == "성장"])
            _stable_cnt = len(_lc[_lc["분류"] == "안정"])
            _decline_cnt = len(_lc[_lc["분류"] == "쇠퇴"])

            lk1, lk2, lk3, lk4 = st.columns(4)
            lk1.metric("신규 (30일 미만)", f"{_new_cnt}개")
            lk2.metric("성장 (최근 증가)", f"{_grow_cnt}개")
            lk3.metric("안정 (꾸준)", f"{_stable_cnt}개")
            lk4.metric("쇠퇴 (최근 감소)", f"{_decline_cnt}개")

            # 분류별 비율 pie
            _lc_summary = pd.DataFrame({
                "분류": ["신규", "성장", "안정", "쇠퇴"],
                "상품수": [_new_cnt, _grow_cnt, _stable_cnt, _decline_cnt]
            })
            _lc_summary = _lc_summary[_lc_summary["상품수"] > 0]
            if not _lc_summary.empty:
                _lc_colors = {"신규": "#3498db", "성장": "#2ecc71", "안정": "#f39c12", "쇠퇴": "#e74c3c"}
                fig_lc = px.pie(_lc_summary, values="상품수", names="분류",
                                title="상품 수명주기 분포",
                                color="분류", color_discrete_map=_lc_colors, hole=0.4)
                fig_lc.update_layout(margin=dict(t=40, b=10, l=10, r=10), height=300)
                st.plotly_chart(fig_lc, width="stretch")

            # 분류별 상세 테이블
            _lc_filter = st.selectbox("분류 필터", ["전체", "신규", "성장", "안정", "쇠퇴"], key="lc_filter")
            _lc_show = _lc.copy()
            if _lc_filter != "전체":
                _lc_show = _lc_show[_lc_show["분류"] == _lc_filter]

            _lc_display = _lc_show[["product_name", "분류", "first_sale", "last_sale", "total_orders", "active_months", "recent_orders", "prev_orders"]].rename(columns={
                "product_name": "상품명", "first_sale": "첫판매일", "last_sale": "최근판매일",
                "total_orders": "총주문수", "active_months": "활동월수",
                "recent_orders": "최근3M주문", "prev_orders": "이전3M주문",
            }).sort_values("총주문수", ascending=False).head(50)

            st.caption(f"총 {len(_lc_show)}개 상품 (상위 50개 표시)")
            st.dataframe(_lc_display, width="stretch", hide_index=True)


# ═══════════════════════════════════════
# 정산
# ═══════════════════════════════════════
elif page == "정산":
    st.title("정산 내역")

    def _fmt_krw_s(val):
        """한국식 금액 표시"""
        val = int(val)
        if abs(val) >= 100_000_000:
            return f"₩{val / 100_000_000:.1f}억"
        elif abs(val) >= 10_000:
            return f"₩{val / 10_000:.0f}만"
        else:
            return f"₩{val:,}"

    # settlement_history 테이블 보장
    with engine.connect() as _conn:
        _conn.execute(text("""
            CREATE TABLE IF NOT EXISTS settlement_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                year_month VARCHAR(7) NOT NULL,
                settlement_type VARCHAR(20),
                settlement_date VARCHAR(10),
                settlement_status VARCHAR(20),
                revenue_date_from VARCHAR(10),
                revenue_date_to VARCHAR(10),
                total_sale INTEGER DEFAULT 0,
                service_fee INTEGER DEFAULT 0,
                settlement_target_amount INTEGER DEFAULT 0,
                settlement_amount INTEGER DEFAULT 0,
                last_amount INTEGER DEFAULT 0,
                pending_released_amount INTEGER DEFAULT 0,
                seller_discount_coupon INTEGER DEFAULT 0,
                downloadable_coupon INTEGER DEFAULT 0,
                seller_service_fee INTEGER DEFAULT 0,
                courantee_fee INTEGER DEFAULT 0,
                deduction_amount INTEGER DEFAULT 0,
                debt_of_last_week INTEGER DEFAULT 0,
                final_amount INTEGER DEFAULT 0,
                bank_name VARCHAR(50),
                bank_account VARCHAR(50),
                raw_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, year_month, settlement_type, settlement_date)
            )
        """))
        _conn.execute(text("CREATE INDEX IF NOT EXISTS ix_settle_account_month ON settlement_history(account_id, year_month)"))
        _conn.execute(text("CREATE INDEX IF NOT EXISTS ix_settle_month ON settlement_history(year_month)"))
        _conn.commit()

    # ── 상단 컨트롤 ──
    from scripts.sync_settlement import SettlementSync

    # 최근 6개월 목록 생성
    from datetime import date as _s_date
    _s_today = _s_date.today()
    _all_months = []
    for _mi in range(12):
        _y = _s_today.year
        _m = _s_today.month - _mi
        while _m <= 0:
            _m += 12
            _y -= 1
        _all_months.append(f"{_y:04d}-{_m:02d}")

    sc1, sc2, sc3 = st.columns([3, 3, 2])
    with sc1:
        settle_months = st.multiselect("월 선택", _all_months, default=_all_months[:6], key="settle_months")
    with sc2:
        settle_acct_filter = st.selectbox("계정", ["전체"] + account_names, key="settle_acct")
    with sc3:
        st.markdown("<br>", unsafe_allow_html=True)
        btn_settle_sync = st.button("정산 동기화", type="primary", key="btn_settle_sync", width="stretch")

    # 동기화 실행
    if btn_settle_sync:
        try:
            syncer = SettlementSync(db_path=str(DB_PATH))
            acct_arg = None if settle_acct_filter == "전체" else settle_acct_filter
            sync_prog = st.progress(0, text="정산 동기화 중...")
            results = syncer.sync_all(
                months=len(settle_months), account_name=acct_arg,
                progress_callback=lambda cur, tot, msg: sync_prog.progress(
                    min(cur / max(tot, 1), 1.0), text=msg),
            )
            sync_prog.progress(1.0, text="완료!")
            total_f = sum(r["fetched"] for r in results)
            total_u = sum(r["upserted"] for r in results)
            st.success(f"동기화 완료: {len(results)}개 계정, 조회 {total_f:,}건, 저장 {total_u:,}건")
            query_df.clear()
        except Exception as e:
            st.error(f"동기화 오류: {e}")
            logger.exception("정산 동기화 오류")

    st.divider()

    # ── 계정 필터 ──
    _s_acct_where = ""
    if settle_acct_filter != "전체":
        _s_aid_row = query_df("SELECT id FROM accounts WHERE account_name = :name LIMIT 1", {"name": settle_acct_filter})
        if _s_aid_row.empty:
            st.error(f"계정 '{settle_acct_filter}'을 찾을 수 없습니다.")
            st.stop()
        _s_acct_id = int(_s_aid_row.iloc[0]["id"])
        _s_acct_where = f"AND s.account_id = {_s_acct_id}"

    # 월 필터 조건
    if not settle_months:
        st.info("월을 선택하세요.")
        st.stop()
    _months_in = ",".join(f"'{m}'" for m in settle_months)
    _s_month_where = f"AND s.year_month IN ({_months_in})"

    # ── KPI (WEEKLY+MONTHLY 집계 — RESERVE는 중복이므로 제외) ──
    _s_kpi = query_df(f"""
        SELECT
            COALESCE(SUM(s.total_sale), 0) as total_sale,
            COALESCE(SUM(s.service_fee), 0) as service_fee,
            COALESCE(SUM(s.settlement_target_amount), 0) as target_amount,
            COALESCE(SUM(s.last_amount), 0) as last_amount,
            COALESCE(SUM(s.settlement_amount), 0) as settlement_amount,
            COALESCE(SUM(s.seller_service_fee), 0) as seller_service_fee,
            COALESCE(SUM(s.seller_discount_coupon), 0) as seller_coupon,
            COALESCE(SUM(s.downloadable_coupon), 0) as dl_coupon,
            COALESCE(SUM(s.courantee_fee), 0) as courantee_fee,
            COALESCE(SUM(s.deduction_amount), 0) as deduction_amount,
            COALESCE(SUM(s.debt_of_last_week), 0) as debt_of_last_week,
            COALESCE(SUM(s.pending_released_amount), 0) as pending_released,
            COALESCE(SUM(s.final_amount), 0) as final_amount
        FROM settlement_history s
        WHERE s.settlement_type IN ('WEEKLY', 'MONTHLY') {_s_acct_where} {_s_month_where}
    """)

    if _s_kpi.empty or int(_s_kpi.iloc[0]["total_sale"]) == 0:
        st.info("해당 기간 정산 데이터가 없습니다. '정산 동기화' 버튼을 눌러주세요.")
        st.stop()

    _sk = _s_kpi.iloc[0]
    _s_total_sale = int(_sk["total_sale"])
    _s_final = int(_sk["final_amount"])
    _s_total_deduct = _s_total_sale - _s_final
    _s_receive_rate = round(_s_final / _s_total_sale * 100, 1) if _s_total_sale > 0 else 0

    sk1, sk2, sk3, sk4 = st.columns(4)
    sk1.metric("총판매액", _fmt_krw_s(_s_total_sale))
    sk2.metric("실지급액", _fmt_krw_s(_s_final))
    sk3.metric("총차감액", _fmt_krw_s(_s_total_deduct))
    sk4.metric("수취율", f"{_s_receive_rate}%")

    st.caption(f"선택 기간: {settle_months[-1]} ~ {settle_months[0]}")

    # ── 차감 내역 상세 ──
    _sv = lambda k: abs(int(_sk[k]))
    _breakdown = [
        ("총판매액", _s_total_sale, ""),
        ("판매수수료", _sv("service_fee"), f'{round(_sv("service_fee")/_s_total_sale*100,1)}%' if _s_total_sale else ""),
        ("= 정산대상액", int(_sk["target_amount"]), ""),
        ("유보금 (RESERVE 환급)", _sv("last_amount"), f'{round(_sv("last_amount")/_s_total_sale*100,1)}%' if _s_total_sale else ""),
        ("= 지급액", int(_sk["settlement_amount"]), ""),
    ]
    # 0이 아닌 차감 항목만 추가
    _extra_deductions = [
        ("seller_service_fee", "광고비 (판매자서비스수수료)"),
        ("deduction_amount", "차감금"),
        ("debt_of_last_week", "전주 이월금"),
        ("courantee_fee", "보증수수료"),
        ("seller_coupon", "판매자할인쿠폰"),
        ("dl_coupon", "다운로드쿠폰"),
    ]
    for _ek, _elabel in _extra_deductions:
        _ev = _sv(_ek)
        if _ev > 0:
            _breakdown.append((_elabel, _ev, ""))
    _pending = int(_sk["pending_released"])
    if _pending > 0:
        _breakdown.append(("+ 보류해제금", _pending, ""))
    _breakdown.append(("= 실지급액 (finalAmount)", _s_final, f"{_s_receive_rate}%"))

    with st.expander("차감 내역 상세", expanded=True):
        _bd_data = []
        for _label, _val, _note in _breakdown:
            is_result = _label.startswith("=") or _label.startswith("+")
            if is_result:
                _bd_data.append({"항목": _label, "금액": f"{_val:,}", "비고": _note})
            else:
                _bd_data.append({"항목": f"  - {_label}" if _bd_data else _label, "금액": f"{_val:,}", "비고": _note})
        _bd_df = pd.DataFrame(_bd_data)
        # = 으로 시작하는 소계 행 강조
        def _highlight_subtotal(row):
            if str(row["항목"]).startswith("="):
                return ["font-weight: bold; background-color: #f0f2f6"] * len(row)
            return [""] * len(row)
        st.dataframe(_bd_df.style.apply(_highlight_subtotal, axis=1), width="stretch", hide_index=True)

    # ── 월별 추이 차트 (WEEKLY+MONTHLY) ──
    _s_monthly = query_df(f"""
        SELECT s.year_month as 월,
            SUM(s.total_sale) as 총판매액,
            SUM(s.final_amount) as 실지급액,
            SUM(s.total_sale) - SUM(s.final_amount) as 차감액
        FROM settlement_history s
        WHERE s.settlement_type IN ('WEEKLY', 'MONTHLY') {_s_acct_where} {_s_month_where}
        GROUP BY s.year_month ORDER BY s.year_month
    """)
    if not _s_monthly.empty:
        st.bar_chart(_s_monthly.set_index("월")[["총판매액", "실지급액"]])

    st.divider()

    # ── 하단 탭 3개 ──
    stab1, stab2, stab3 = st.tabs(["📊 계정별 비교", "📅 월별 상세", "📋 정산 상태"])

    with stab1:
        _s_acct_cmp = query_df(f"""
            SELECT a.account_name as 계정,
                SUM(s.total_sale) as 총판매액,
                SUM(s.final_amount) as 실지급액,
                SUM(s.total_sale) - SUM(s.final_amount) as 차감액,
                ROUND(SUM(s.final_amount) * 100.0 / NULLIF(SUM(s.total_sale), 0), 1) as '수취율(%)'
            FROM settlement_history s
            JOIN accounts a ON s.account_id = a.id
            WHERE s.settlement_type IN ('WEEKLY', 'MONTHLY') {_s_month_where}
            GROUP BY s.account_id ORDER BY 총판매액 DESC
        """)
        if not _s_acct_cmp.empty:
            _sc_chart, _sc_pie = st.columns([3, 2])
            with _sc_chart:
                st.bar_chart(_s_acct_cmp.set_index("계정")[["총판매액", "실지급액"]])
            with _sc_pie:
                import plotly.express as px
                _s_pie = _s_acct_cmp[_s_acct_cmp["총판매액"] > 0]
                if not _s_pie.empty:
                    fig = px.pie(_s_pie, values="실지급액", names="계정", title="실지급 비중",
                                 hole=0.4, color_discrete_sequence=px.colors.qualitative.Set2)
                    fig.update_layout(margin=dict(t=40, b=10, l=10, r=10), height=300, showlegend=True)
                    st.plotly_chart(fig, width="stretch")
            st.dataframe(fmt_money_df(_s_acct_cmp), width="stretch", hide_index=True)
            _csv_s_acct = _s_acct_cmp.to_csv(index=False).encode("utf-8-sig")
            st.download_button("CSV 다운로드", _csv_s_acct, "settlement_accounts.csv", "text/csv", key="dl_s_acct")
        else:
            st.info("계정별 데이터가 없습니다.")

    with stab2:
        _s_detail = query_df(f"""
            SELECT a.account_name as 계정,
                s.year_month as 월,
                s.settlement_type as 유형,
                s.settlement_date as 정산일,
                s.settlement_status as 상태,
                s.total_sale as 총판매액,
                s.service_fee as 수수료,
                s.settlement_target_amount as 정산대상액,
                s.settlement_amount as 지급액,
                s.last_amount as 유보금,
                s.final_amount as 최종지급액,
                s.revenue_date_from as '매출시작',
                s.revenue_date_to as '매출종료'
            FROM settlement_history s
            JOIN accounts a ON s.account_id = a.id
            WHERE 1=1 {_s_acct_where} {_s_month_where}
            ORDER BY s.year_month DESC, a.account_name, s.settlement_date
        """)
        if not _s_detail.empty:
            st.caption(f"총 {len(_s_detail)}건")
            st.dataframe(fmt_money_df(_s_detail), width="stretch", hide_index=True)
            _csv_s_det = _s_detail.to_csv(index=False).encode("utf-8-sig")
            st.download_button("CSV 다운로드", _csv_s_det, "settlement_detail.csv", "text/csv", key="dl_s_det")
        else:
            st.info("상세 데이터가 없습니다.")

    with stab3:
        # DONE/SUBJECT 집계
        _s_status = query_df(f"""
            SELECT s.settlement_status as 상태,
                COUNT(*) as 건수,
                SUM(s.total_sale) as 총판매액,
                SUM(s.final_amount) as 최종지급액
            FROM settlement_history s
            WHERE 1=1 {_s_acct_where} {_s_month_where}
            GROUP BY s.settlement_status
        """)
        if not _s_status.empty:
            _st1, _st2 = st.columns(2)
            _done = _s_status[_s_status["상태"] == "DONE"]
            _subj = _s_status[_s_status["상태"] == "SUBJECT"]
            with _st1:
                _done_amt = int(_done["최종지급액"].sum()) if not _done.empty else 0
                _done_cnt = int(_done["건수"].sum()) if not _done.empty else 0
                st.metric("정산 완료 (DONE)", f"{_done_cnt}건 / {_fmt_krw_s(_done_amt)}")
            with _st2:
                _subj_amt = int(_subj["최종지급액"].sum()) if not _subj.empty else 0
                _subj_cnt = int(_subj["건수"].sum()) if not _subj.empty else 0
                st.metric("정산 예정 (SUBJECT)", f"{_subj_cnt}건 / {_fmt_krw_s(_subj_amt)}")

            st.dataframe(fmt_money_df(_s_status), width="stretch", hide_index=True)

            # 미정산 경고
            if not _subj.empty and _subj_cnt > 0:
                _subj_detail = query_df(f"""
                    SELECT a.account_name as 계정,
                        s.year_month as 월,
                        s.settlement_type as 유형,
                        s.settlement_date as 정산예정일,
                        s.total_sale as 총판매액,
                        s.final_amount as 지급예정액
                    FROM settlement_history s
                    JOIN accounts a ON s.account_id = a.id
                    WHERE s.settlement_status = 'SUBJECT'
                        {_s_acct_where.replace('s.account_id', 's.account_id')} {_s_month_where}
                    ORDER BY s.settlement_date
                """)
                if not _subj_detail.empty:
                    st.warning(f"미정산 {_subj_cnt}건이 남아있습니다.")
                    st.dataframe(fmt_money_df(_subj_detail), width="stretch", hide_index=True)
        else:
            st.info("정산 상태 데이터가 없습니다.")


# ═══════════════════════════════════════
# 광고
# ═══════════════════════════════════════
elif page == "광고":
    st.title("광고 분석")

    def _fmt_krw_ad(val):
        """한국식 금액 표시"""
        val = int(val)
        if abs(val) >= 100_000_000:
            return f"₩{val / 100_000_000:.1f}억"
        elif abs(val) >= 10_000:
            return f"₩{val / 10_000:.0f}만"
        else:
            return f"₩{val:,}"

    # ad_spends 테이블 보장
    with engine.connect() as _conn:
        _conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ad_spends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                ad_date DATE NOT NULL,
                campaign_id VARCHAR(50) NOT NULL,
                campaign_name VARCHAR(200),
                ad_type VARCHAR(20),
                ad_objective VARCHAR(50),
                daily_budget INTEGER DEFAULT 0,
                spent_amount INTEGER DEFAULT 0,
                adjustment INTEGER DEFAULT 0,
                spent_after_adjust INTEGER DEFAULT 0,
                over_spend INTEGER DEFAULT 0,
                billable_cost INTEGER DEFAULT 0,
                vat_amount INTEGER DEFAULT 0,
                total_charge INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, ad_date, campaign_id)
            )
        """))
        _conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ad_account_date ON ad_spends(account_id, ad_date)"))
        _conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ad_date ON ad_spends(ad_date)"))
        _conn.commit()

    # ── 상단 컨트롤 ──
    ad_c1, ad_c2, ad_c3 = st.columns([3, 3, 2])
    with ad_c1:
        ad_acct_filter = st.selectbox("계정", ["전체"] + account_names, key="ad_acct")
    with ad_c2:
        from datetime import date as _ad_date, timedelta as _ad_td
        _ad_today = _ad_date.today()
        _ad_default_from = _ad_today.replace(day=1)
        _ad_date_range = st.date_input(
            "기간", value=(_ad_default_from, _ad_today), key="ad_dates"
        )
        if isinstance(_ad_date_range, tuple) and len(_ad_date_range) == 2:
            _ad_from, _ad_to = _ad_date_range
        else:
            _ad_from, _ad_to = _ad_default_from, _ad_today
    with ad_c3:
        st.markdown("<br>", unsafe_allow_html=True)
        ad_uploaded = st.file_uploader("Excel 업로드", type=["xlsx"], key="ad_upload",
                                       label_visibility="collapsed")

    # ── Excel 업로드 처리 ──
    if ad_uploaded is not None:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx",
                                          prefix=ad_uploaded.name.replace(".xlsx", "_")) as tmp:
            tmp.write(ad_uploaded.read())
            tmp_path = tmp.name

        try:
            from scripts.sync_ad_spend import AdSpendSync
            syncer = AdSpendSync(db_path=str(DB_PATH))
            result = syncer.sync_file(tmp_path)

            if result.get("error"):
                st.error(f"업로드 오류: {result['error']}")
            else:
                st.success(
                    f"업로드 완료: {result['account']} | {result['period']} | "
                    f"파싱 {result['parsed']}건, 저장 {result['saved']}건"
                )
                query_df.clear()
        except Exception as e:
            st.error(f"파싱 오류: {e}")
            logger.exception("광고 Excel 파싱 오류")
        finally:
            os.unlink(tmp_path)

    st.divider()

    # ── 계정/기간 필터 ──
    _ad_acct_where = ""
    if ad_acct_filter != "전체":
        _ad_aid_row = query_df("SELECT id FROM accounts WHERE account_name = :name LIMIT 1",
                               {"name": ad_acct_filter})
        if _ad_aid_row.empty:
            st.error(f"계정 '{ad_acct_filter}'을 찾을 수 없습니다.")
            st.stop()
        _ad_acct_id = int(_ad_aid_row.iloc[0]["id"])
        _ad_acct_where = f"AND a.account_id = {_ad_acct_id}"

    _ad_from_str = _ad_from.isoformat()
    _ad_to_str = _ad_to.isoformat()
    _ad_date_where = f"AND a.ad_date BETWEEN '{_ad_from_str}' AND '{_ad_to_str}'"

    # ── 데이터 존재 확인 ──
    _ad_count = query_df(f"""
        SELECT COUNT(*) as cnt FROM ad_spends a
        WHERE 1=1 {_ad_acct_where} {_ad_date_where}
    """)
    _ad_total_rows = int(_ad_count.iloc[0]["cnt"]) if not _ad_count.empty else 0

    if _ad_total_rows == 0:
        st.info("해당 기간 광고 데이터가 없습니다. Excel 파일을 업로드해주세요.")
        st.stop()

    # ── KPI 카드 4개 ──
    _ad_kpi = query_df(f"""
        SELECT
            COALESCE(SUM(a.billable_cost), 0) as total_cost,
            COUNT(DISTINCT a.ad_date) as active_days,
            COALESCE(SUM(a.vat_amount), 0) as total_vat,
            COALESCE(SUM(a.total_charge), 0) as total_charge
        FROM ad_spends a
        WHERE 1=1 {_ad_acct_where} {_ad_date_where}
    """)
    _adk = _ad_kpi.iloc[0]
    _ad_total_cost = int(_adk["total_cost"])
    _ad_active_days = int(_adk["active_days"])
    _ad_daily_avg = _ad_total_cost // max(_ad_active_days, 1)

    # 매출 데이터 크로스 (revenue_history)
    _ad_rev_where = _ad_acct_where.replace("a.account_id", "r.account_id")
    _ad_rev = query_df(f"""
        SELECT
            COALESCE(SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END), 0) as revenue,
            COALESCE(SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END), 0) as settlement
        FROM revenue_history r
        WHERE r.recognition_date BETWEEN '{_ad_from_str}' AND '{_ad_to_str}'
            {_ad_rev_where}
    """)
    _ad_revenue = int(_ad_rev.iloc[0]["revenue"]) if not _ad_rev.empty else 0
    _ad_settlement = int(_ad_rev.iloc[0]["settlement"]) if not _ad_rev.empty else 0
    _ad_roas = round(_ad_revenue / _ad_total_cost, 2) if _ad_total_cost > 0 else 0
    _ad_profit = _ad_settlement - _ad_total_cost

    adk1, adk2, adk3, adk4 = st.columns(4)
    adk1.metric("총 광고비", _fmt_krw_ad(_ad_total_cost))
    adk2.metric("일평균 광고비", _fmt_krw_ad(_ad_daily_avg),
                delta=f"{_ad_active_days}일 운영")
    adk3.metric("ROAS", f"{_ad_roas:.1f}x" if _ad_roas > 0 else "-",
                delta=f"매출 {_fmt_krw_ad(_ad_revenue)}" if _ad_revenue > 0 else "매출 데이터 없음",
                delta_color="normal")
    adk4.metric("순이익", _fmt_krw_ad(_ad_profit) if _ad_settlement > 0 else "-",
                delta=f"정산 {_fmt_krw_ad(_ad_settlement)}" if _ad_settlement > 0 else "정산 데이터 없음",
                delta_color="normal" if _ad_profit >= 0 else "inverse")

    st.caption(f"기간: {_ad_from_str} ~ {_ad_to_str} | 데이터 {_ad_total_rows}건")

    # ── 일별 추이 차트 ──
    _ad_daily = query_df(f"""
        SELECT a.ad_date as 날짜,
               SUM(a.billable_cost) as 광고비
        FROM ad_spends a
        WHERE 1=1 {_ad_acct_where} {_ad_date_where}
        GROUP BY a.ad_date ORDER BY a.ad_date
    """)

    _ad_rev_daily = query_df(f"""
        SELECT r.recognition_date as 날짜,
               SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as 매출
        FROM revenue_history r
        WHERE r.recognition_date BETWEEN '{_ad_from_str}' AND '{_ad_to_str}'
            {_ad_rev_where}
        GROUP BY r.recognition_date ORDER BY r.recognition_date
    """)

    if not _ad_daily.empty:
        _ad_chart = _ad_daily.copy()
        _ad_chart["날짜"] = pd.to_datetime(_ad_chart["날짜"])
        if not _ad_rev_daily.empty:
            _ad_rev_daily["날짜"] = pd.to_datetime(_ad_rev_daily["날짜"])
            _ad_chart = _ad_chart.merge(_ad_rev_daily, on="날짜", how="outer").sort_values("날짜")
            _ad_chart = _ad_chart.fillna(0)

        import plotly.graph_objects as go
        _fig_ad = go.Figure()
        _fig_ad.add_trace(go.Bar(
            x=_ad_chart["날짜"], y=_ad_chart["광고비"],
            name="광고비", marker_color="#FF6B6B", opacity=0.7
        ))
        if "매출" in _ad_chart.columns:
            _fig_ad.add_trace(go.Scatter(
                x=_ad_chart["날짜"], y=_ad_chart["매출"],
                name="매출", mode="lines+markers",
                line=dict(color="#4ECDC4", width=2)
            ))
        _fig_ad.update_layout(
            title="일별 광고비 vs 매출",
            xaxis_title="날짜", yaxis_title="금액 (원)",
            barmode="overlay", height=400,
            margin=dict(t=40, b=40, l=60, r=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(_fig_ad, use_container_width=True)

    st.divider()

    # ── 하단 탭 3개 ──
    ad_tab1, ad_tab2, ad_tab3 = st.tabs(["📅 일별 상세", "🎯 캠페인별", "📊 ROI 분석"])

    with ad_tab1:
        _ad_detail = query_df(f"""
            SELECT a.ad_date as 날짜,
                   act.account_name as 계정,
                   SUM(a.billable_cost) as 광고비,
                   SUM(a.vat_amount) as 부가세,
                   SUM(a.total_charge) as 총청구,
                   COALESCE(r.매출, 0) as 매출,
                   COALESCE(r.정산, 0) as 정산,
                   CASE WHEN SUM(a.billable_cost) > 0
                        THEN ROUND(COALESCE(r.매출, 0) * 1.0 / SUM(a.billable_cost), 2)
                        ELSE 0 END as ROAS
            FROM ad_spends a
            JOIN accounts act ON a.account_id = act.id
            LEFT JOIN (
                SELECT recognition_date as rd, account_id as aid,
                       SUM(CASE WHEN sale_type='SALE' THEN sale_amount ELSE -sale_amount END) as 매출,
                       SUM(CASE WHEN sale_type='SALE' THEN settlement_amount ELSE -settlement_amount END) as 정산
                FROM revenue_history
                GROUP BY recognition_date, account_id
            ) r ON a.ad_date = r.rd AND a.account_id = r.aid
            WHERE 1=1 {_ad_acct_where} {_ad_date_where}
            GROUP BY a.ad_date, a.account_id
            ORDER BY a.ad_date DESC
        """)
        if not _ad_detail.empty:
            st.caption(f"총 {len(_ad_detail)}건")
            _ad_money_kw = ["광고비", "부가세", "총청구", "매출", "정산"]
            _disp = _ad_detail.copy()
            for _mk in _ad_money_kw:
                if _mk in _disp.columns and pd.api.types.is_numeric_dtype(_disp[_mk]):
                    _disp[_mk] = _disp[_mk].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")
            st.dataframe(_disp, width="stretch", hide_index=True)
            _csv_ad = _ad_detail.to_csv(index=False).encode("utf-8-sig")
            st.download_button("CSV 다운로드", _csv_ad, "ad_daily_detail.csv", "text/csv", key="dl_ad_daily")
        else:
            st.info("일별 상세 데이터가 없습니다.")

    with ad_tab2:
        _ad_camp = query_df(f"""
            SELECT a.campaign_id as 캠페인ID,
                   a.campaign_name as 캠페인명,
                   a.ad_type as 광고유형,
                   a.ad_objective as 광고목표,
                   SUM(a.billable_cost) as 총광고비,
                   COUNT(DISTINCT a.ad_date) as 운영일수,
                   ROUND(SUM(a.billable_cost) * 1.0 / COUNT(DISTINCT a.ad_date)) as 일평균광고비,
                   SUM(a.daily_budget) as 총예산,
                   MIN(a.ad_date) as 시작일,
                   MAX(a.ad_date) as 종료일
            FROM ad_spends a
            WHERE 1=1 {_ad_acct_where} {_ad_date_where}
            GROUP BY a.campaign_id, a.campaign_name, a.ad_type, a.ad_objective
            ORDER BY 총광고비 DESC
        """)
        if not _ad_camp.empty:
            _camp_money = ["총광고비", "일평균광고비", "총예산"]
            _camp_disp = _ad_camp.copy()
            for _mk in _camp_money:
                if _mk in _camp_disp.columns and pd.api.types.is_numeric_dtype(_camp_disp[_mk]):
                    _camp_disp[_mk] = _camp_disp[_mk].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")
            st.dataframe(_camp_disp, width="stretch", hide_index=True)
        else:
            st.info("캠페인 데이터가 없습니다.")

    with ad_tab3:
        # ROI 분석: 광고비 대비 매출/정산 효율
        st.subheader("광고 효율 요약")

        _roi_c1, _roi_c2, _roi_c3 = st.columns(3)
        with _roi_c1:
            st.metric("총 광고비 (VAT 제외)", _fmt_krw_ad(_ad_total_cost))
        with _roi_c2:
            _ad_cost_ratio = round(_ad_total_cost / _ad_revenue * 100, 1) if _ad_revenue > 0 else 0
            st.metric("광고비/매출 비율", f"{_ad_cost_ratio}%" if _ad_cost_ratio > 0 else "-")
        with _roi_c3:
            _ad_profit_margin = round(_ad_profit / _ad_revenue * 100, 1) if _ad_revenue > 0 else 0
            st.metric("순이익률", f"{_ad_profit_margin}%" if _ad_revenue > 0 else "-",
                      delta_color="normal" if _ad_profit_margin >= 0 else "inverse")

        # 요일별 패턴
        st.subheader("요일별 광고비 패턴")
        _ad_dow = query_df(f"""
            SELECT
                CASE CAST(strftime('%w', a.ad_date) AS INTEGER)
                    WHEN 0 THEN '일'
                    WHEN 1 THEN '월'
                    WHEN 2 THEN '화'
                    WHEN 3 THEN '수'
                    WHEN 4 THEN '목'
                    WHEN 5 THEN '금'
                    WHEN 6 THEN '토'
                END as 요일,
                CAST(strftime('%w', a.ad_date) AS INTEGER) as dow_num,
                ROUND(AVG(a.billable_cost)) as 평균광고비,
                COUNT(*) as 건수
            FROM ad_spends a
            WHERE 1=1 {_ad_acct_where} {_ad_date_where}
            GROUP BY dow_num
            ORDER BY dow_num
        """)
        if not _ad_dow.empty:
            import plotly.express as px
            _fig_dow = px.bar(
                _ad_dow, x="요일", y="평균광고비",
                title="요일별 평균 광고비",
                color="평균광고비",
                color_continuous_scale="RdYlGn_r"
            )
            _fig_dow.update_layout(height=300, margin=dict(t=40, b=40))
            st.plotly_chart(_fig_dow, use_container_width=True)

        # 요일별 매출/광고비 교차
        _ad_dow_rev = query_df(f"""
            SELECT
                CASE CAST(strftime('%w', a.ad_date) AS INTEGER)
                    WHEN 0 THEN '일'
                    WHEN 1 THEN '월'
                    WHEN 2 THEN '화'
                    WHEN 3 THEN '수'
                    WHEN 4 THEN '목'
                    WHEN 5 THEN '금'
                    WHEN 6 THEN '토'
                END as 요일,
                CAST(strftime('%w', a.ad_date) AS INTEGER) as dow_num,
                ROUND(AVG(a.billable_cost)) as 평균광고비,
                ROUND(AVG(COALESCE(r.매출, 0))) as 평균매출,
                CASE WHEN AVG(a.billable_cost) > 0
                     THEN ROUND(AVG(COALESCE(r.매출, 0)) / AVG(a.billable_cost), 2)
                     ELSE 0 END as 평균ROAS
            FROM ad_spends a
            LEFT JOIN (
                SELECT recognition_date as rd, account_id as aid,
                       SUM(CASE WHEN sale_type='SALE' THEN sale_amount ELSE -sale_amount END) as 매출
                FROM revenue_history
                GROUP BY recognition_date, account_id
            ) r ON a.ad_date = r.rd AND a.account_id = r.aid
            WHERE 1=1 {_ad_acct_where} {_ad_date_where}
            GROUP BY dow_num
            ORDER BY dow_num
        """)
        if not _ad_dow_rev.empty:
            _dow_disp = _ad_dow_rev[["요일", "평균광고비", "평균매출", "평균ROAS"]].copy()
            for _mk in ["평균광고비", "평균매출"]:
                if _mk in _dow_disp.columns:
                    _dow_disp[_mk] = _dow_disp[_mk].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")
            st.dataframe(_dow_disp, width="stretch", hide_index=True)


# ═══════════════════════════════════════
# 주문 관리
# ═══════════════════════════════════════
elif page == "주문":
    st.title("주문 관리")

    from datetime import date, timedelta

    # ── 상단 컨트롤 ──
    _ord_ctrl1, _ord_ctrl2, _ord_ctrl3, _ord_ctrl4 = st.columns([2, 2, 2, 2])
    with _ord_ctrl1:
        _ord_acct = st.selectbox("계정", ["전체"] + account_names, key="ord_acct")
    with _ord_ctrl2:
        _ord_period = st.selectbox("기간", ["당일", "7일", "14일", "30일", "60일"], key="ord_period")
    with _ord_ctrl3:
        _ord_status_filter = st.selectbox("상태", ["전체", "ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING", "FINAL_DELIVERY", "NONE_TRACKING"], key="ord_status")
    with _ord_ctrl4:
        st.markdown("<br>", unsafe_allow_html=True)
        _btn_ord_sync = st.button("주문 동기화", type="primary", key="btn_ord_sync", use_container_width=True)

    # 기간 계산
    _ord_days = 0 if _ord_period == "당일" else int(_ord_period.replace("일", ""))
    _ord_date_to = date.today()
    _ord_date_from = _ord_date_to if _ord_days == 0 else _ord_date_to - timedelta(days=_ord_days)
    _ord_date_from_str = _ord_date_from.isoformat()
    _ord_date_to_str = _ord_date_to.isoformat()

    # 계정/상태 WHERE 절
    _ord_acct_where = ""
    _ord_acct_params = {}
    if _ord_acct != "전체":
        _ord_acct_where = "AND o.account_id = (SELECT id FROM accounts WHERE account_name = :acct_name)"
        _ord_acct_params["acct_name"] = _ord_acct

    _ord_status_where = ""
    if _ord_status_filter != "전체":
        _ord_status_where = f"AND o.status = '{_ord_status_filter}'"

    _ord_date_where = f"AND o.ordered_at >= '{_ord_date_from_str}' AND o.ordered_at <= '{_ord_date_to_str} 23:59:59'"

    # 동기화 실행
    if _btn_ord_sync:
        with st.spinner("주문 데이터 동기화 중..."):
            try:
                from scripts.sync_orders import OrderSync
                _ord_syncer = OrderSync()
                _sync_acct = _ord_acct if _ord_acct != "전체" else None
                _ord_progress = st.progress(0, text="동기화 시작...")
                def _ord_progress_cb(current, total, msg):
                    if total > 0:
                        _ord_progress.progress(current / total, text=msg)
                _ord_results = _ord_syncer.sync_all(
                    days=_ord_days,
                    account_name=_sync_acct,
                    progress_callback=_ord_progress_cb,
                )
                _total_f = sum(r["fetched"] for r in _ord_results)
                _total_u = sum(r["upserted"] for r in _ord_results)
                st.success(f"동기화 완료! 조회 {_total_f:,}건, 저장 {_total_u:,}건")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"동기화 오류: {e}")

    # ── 테이블 존재 확인 ──
    _ord_table_exists = False
    try:
        _ord_check = query_df("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
        _ord_table_exists = not _ord_check.empty
    except Exception:
        pass

    if not _ord_table_exists:
        st.info("orders 테이블이 없습니다. '주문 동기화' 버튼을 눌러 데이터를 가져오세요.")
    else:
        # ── KPI 카드 ──
        _ord_kpi_sql_base = f"""
            FROM orders o
            WHERE 1=1 {_ord_acct_where} {_ord_date_where}
        """

        _ord_total = int(query_df(f"SELECT COUNT(*) as c {_ord_kpi_sql_base}", _ord_acct_params).iloc[0]["c"])
        _ord_total_sales = int(query_df(f"SELECT COALESCE(SUM(o.order_price), 0) as s {_ord_kpi_sql_base}", _ord_acct_params).iloc[0]["s"])
        _ord_delivered = int(query_df(f"SELECT COUNT(*) as c {_ord_kpi_sql_base} AND o.status = 'FINAL_DELIVERY'", _ord_acct_params).iloc[0]["c"])
        _ord_canceled = int(query_df(f"SELECT COUNT(*) as c {_ord_kpi_sql_base} AND (o.canceled = 1 OR o.cancel_count > 0)", _ord_acct_params).iloc[0]["c"])

        _ord_delivery_pct = ((_ord_delivered / _ord_total * 100) if _ord_total > 0 else 0)

        def _ord_fmt_krw(val):
            val = int(val)
            if abs(val) >= 100_000_000:
                return f"{val / 100_000_000:.1f}억"
            elif abs(val) >= 10_000:
                return f"{val / 10_000:.0f}만"
            else:
                return f"{val:,}"

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("총 주문 수", f"{_ord_total:,}건")
        k2.metric("총 매출액", f"₩{_ord_fmt_krw(_ord_total_sales)}")
        k3.metric("배송완료율", f"{_ord_delivery_pct:.1f}%")
        k4.metric("취소/환불", f"{_ord_canceled:,}건")

        st.divider()

        # ── 일별 주문 추이 ──
        _ord_daily = query_df(f"""
            SELECT DATE(o.ordered_at) as 날짜,
                   COUNT(*) as 주문수,
                   COALESCE(SUM(o.order_price), 0) as 매출액
            {_ord_kpi_sql_base}
            GROUP BY DATE(o.ordered_at)
            ORDER BY 날짜
        """, _ord_acct_params)

        if not _ord_daily.empty:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots

            _ord_fig = make_subplots(specs=[[{"secondary_y": True}]])
            _ord_fig.add_trace(
                go.Bar(x=_ord_daily["날짜"], y=_ord_daily["주문수"], name="주문 수", marker_color="#636EFA"),
                secondary_y=False,
            )
            _ord_fig.add_trace(
                go.Scatter(x=_ord_daily["날짜"], y=_ord_daily["매출액"], name="매출액", line=dict(color="#EF553B", width=2)),
                secondary_y=True,
            )
            _ord_fig.update_layout(
                title="일별 주문 추이",
                height=350,
                margin=dict(l=20, r=20, t=40, b=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            _ord_fig.update_yaxes(title_text="주문 수", secondary_y=False)
            _ord_fig.update_yaxes(title_text="매출액 (원)", secondary_y=True)
            st.plotly_chart(_ord_fig, use_container_width=True)

        st.divider()

        # ── 3개 탭 ──
        _ord_tab1, _ord_tab2, _ord_tab3 = st.tabs(["주문 목록", "상태별 분석", "배송 관리"])

        # ── 탭1: 주문 목록 ──
        with _ord_tab1:
            _ord_list = query_df(f"""
                SELECT
                    a.account_name as 계정,
                    o.order_id as 주문번호,
                    o.shipment_box_id as 묶음배송번호,
                    DATE(o.ordered_at) as 주문일,
                    o.seller_product_name as 상품명,
                    o.vendor_item_name as 옵션명,
                    o.shipping_count as 수량,
                    o.order_price as 결제금액,
                    o.status as 상태,
                    o.delivery_company_name as 택배사,
                    o.invoice_number as 운송장번호,
                    DATE(o.delivered_date) as 배송완료일,
                    o.receiver_name as 수취인
                FROM orders o
                JOIN accounts a ON o.account_id = a.id
                WHERE 1=1 {_ord_acct_where} {_ord_status_where} {_ord_date_where}
                ORDER BY o.ordered_at DESC
                LIMIT 500
            """, _ord_acct_params)

            if _ord_list.empty:
                st.info("해당 조건의 주문이 없습니다.")
            else:
                # 상태 한글 매핑
                _status_map = {
                    "ACCEPT": "결제완료",
                    "INSTRUCT": "상품준비중",
                    "DEPARTURE": "출고완료",
                    "DELIVERING": "배송중",
                    "FINAL_DELIVERY": "배송완료",
                    "NONE_TRACKING": "추적불가",
                }
                _ord_list["상태"] = _ord_list["상태"].map(lambda x: _status_map.get(x, x))

                # 금액 포맷
                if "결제금액" in _ord_list.columns:
                    _ord_list["결제금액"] = _ord_list["결제금액"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")

                gb = GridOptionsBuilder.from_dataframe(_ord_list)
                gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
                gb.configure_default_column(resizable=True, sorteable=True, filterable=True)
                gb.configure_column("상품명", width=250)
                gb.configure_column("옵션명", width=200)
                grid_opts = gb.build()
                AgGrid(_ord_list, gridOptions=grid_opts, height=500, theme="streamlit")

                # CSV 다운로드
                st.download_button(
                    "CSV 다운로드",
                    _ord_list.to_csv(index=False, encoding="utf-8-sig"),
                    file_name=f"orders_{_ord_date_from_str}_{_ord_date_to_str}.csv",
                    mime="text/csv",
                    key="ord_csv_dl",
                )

        # ── 탭2: 상태별 분석 ──
        with _ord_tab2:
            _ord_by_status = query_df(f"""
                SELECT o.status as 상태,
                       COUNT(*) as 건수,
                       COALESCE(SUM(o.order_price), 0) as 매출액
                FROM orders o
                WHERE 1=1 {_ord_acct_where} {_ord_date_where}
                GROUP BY o.status
                ORDER BY 건수 DESC
            """, _ord_acct_params)

            if not _ord_by_status.empty:
                import plotly.express as px

                _s_col1, _s_col2 = st.columns(2)

                with _s_col1:
                    _status_map2 = {
                        "ACCEPT": "결제완료", "INSTRUCT": "상품준비중", "DEPARTURE": "출고완료",
                        "DELIVERING": "배송중", "FINAL_DELIVERY": "배송완료", "NONE_TRACKING": "추적불가",
                    }
                    _pie_df = _ord_by_status.copy()
                    _pie_df["상태명"] = _pie_df["상태"].map(lambda x: _status_map2.get(x, x))
                    _fig_pie = px.pie(_pie_df, values="건수", names="상태명", title="상태별 주문 비율")
                    _fig_pie.update_layout(height=350, margin=dict(l=20, r=20, t=40, b=20))
                    st.plotly_chart(_fig_pie, use_container_width=True)

                with _s_col2:
                    _bar_df = _ord_by_status.copy()
                    _bar_df["상태명"] = _bar_df["상태"].map(lambda x: _status_map2.get(x, x))
                    _fig_bar = px.bar(_bar_df, x="상태명", y="매출액", title="상태별 매출 비교",
                                      color="상태명")
                    _fig_bar.update_layout(height=350, margin=dict(l=20, r=20, t=40, b=20), showlegend=False)
                    st.plotly_chart(_fig_bar, use_container_width=True)

                # 배송 소요시간 (주문→배송완료)
                _ord_delivery_time = query_df(f"""
                    SELECT
                        ROUND(AVG(JULIANDAY(o.delivered_date) - JULIANDAY(o.ordered_at)), 1) as 평균소요일,
                        ROUND(MIN(JULIANDAY(o.delivered_date) - JULIANDAY(o.ordered_at)), 1) as 최소소요일,
                        ROUND(MAX(JULIANDAY(o.delivered_date) - JULIANDAY(o.ordered_at)), 1) as 최대소요일,
                        COUNT(*) as 건수
                    FROM orders o
                    WHERE o.status = 'FINAL_DELIVERY'
                          AND o.delivered_date IS NOT NULL
                          AND o.ordered_at IS NOT NULL
                          {_ord_acct_where} {_ord_date_where}
                """, _ord_acct_params)

                if not _ord_delivery_time.empty and _ord_delivery_time.iloc[0]["건수"] > 0:
                    st.subheader("배송 소요시간")
                    _dt_row = _ord_delivery_time.iloc[0]
                    _dt1, _dt2, _dt3, _dt4 = st.columns(4)
                    _dt1.metric("평균", f"{_dt_row['평균소요일']}일")
                    _dt2.metric("최소", f"{_dt_row['최소소요일']}일")
                    _dt3.metric("최대", f"{_dt_row['최대소요일']}일")
                    _dt4.metric("완료건수", f"{int(_dt_row['건수']):,}건")
            else:
                st.info("분석할 주문 데이터가 없습니다.")

        # ── 탭3: 배송 관리 ──
        with _ord_tab3:
            if selected_account is None:
                st.warning("사이드바에서 계정을 선택하세요.")
            else:
                _mgmt_account_id = int(selected_account["id"])
                _mgmt_client = create_wing_client(selected_account)

                st.subheader("상품준비중 일괄 처리")
                st.caption("ACCEPT(결제완료) 상태의 주문을 INSTRUCT(상품준비중)으로 변경합니다.")

                _accept_orders = query_df(f"""
                    SELECT o.shipment_box_id as 묶음배송번호,
                           o.order_id as 주문번호,
                           o.seller_product_name as 상품명,
                           o.shipping_count as 수량,
                           o.order_price as 결제금액,
                           DATE(o.ordered_at) as 주문일
                    FROM orders o
                    WHERE o.account_id = :aid AND o.status = 'ACCEPT'
                    ORDER BY o.ordered_at
                """, {"aid": _mgmt_account_id})

                if _accept_orders.empty:
                    st.info("상품준비중 처리할 주문이 없습니다.")
                else:
                    st.dataframe(_accept_orders, width="stretch", hide_index=True)
                    if st.button("전체 상품준비중 처리", type="primary", key="btn_ack_all"):
                        _ack_ids = _accept_orders["묶음배송번호"].unique().tolist()
                        if _mgmt_client:
                            try:
                                _ack_result = _mgmt_client.acknowledge_ordersheets([int(x) for x in _ack_ids])
                                st.success(f"상품준비중 처리 완료: {len(_ack_ids)}건")
                                # DB 상태 업데이트
                                with engine.connect() as conn:
                                    for _sid in _ack_ids:
                                        conn.execute(text(
                                            "UPDATE orders SET status = 'INSTRUCT', updated_at = :now WHERE account_id = :aid AND shipment_box_id = :sid"
                                        ), {"now": datetime.utcnow().isoformat(), "aid": _mgmt_account_id, "sid": int(_sid)})
                                    conn.commit()
                                st.cache_data.clear()
                            except CoupangWingError as e:
                                st.error(f"API 오류: {e}")
                        else:
                            st.error("WING API 클라이언트를 생성할 수 없습니다.")

                st.divider()

                # ── 송장 업로드 ──
                st.subheader("송장 업로드")
                st.caption("INSTRUCT(상품준비중) 상태의 주문에 운송장을 등록합니다.")

                _instruct_orders = query_df(f"""
                    SELECT o.shipment_box_id as 묶음배송번호,
                           o.order_id as 주문번호,
                           o.vendor_item_id as 옵션ID,
                           o.seller_product_name as 상품명,
                           o.shipping_count as 수량,
                           DATE(o.ordered_at) as 주문일
                    FROM orders o
                    WHERE o.account_id = :aid AND o.status = 'INSTRUCT'
                    ORDER BY o.ordered_at
                """, {"aid": _mgmt_account_id})

                if _instruct_orders.empty:
                    st.info("송장 등록할 주문이 없습니다.")
                else:
                    st.dataframe(_instruct_orders, width="stretch", hide_index=True)

                    _inv_col1, _inv_col2 = st.columns(2)
                    with _inv_col1:
                        _delivery_companies = {
                            "CJGLS": "CJ대한통운", "EPOST": "우체국택배", "HANJIN": "한진택배",
                            "LOTTE": "롯데택배", "LOGEN": "로젠택배", "KGB": "KGB택배",
                            "HDEXP": "합동택배",
                        }
                        _sel_company = st.selectbox("택배사", list(_delivery_companies.keys()),
                                                     format_func=lambda x: _delivery_companies[x],
                                                     key="inv_company")
                    with _inv_col2:
                        _inv_number = st.text_input("운송장번호", key="inv_number")

                    if st.button("송장 등록", key="btn_upload_inv"):
                        if not _inv_number:
                            st.warning("운송장번호를 입력하세요.")
                        elif _mgmt_client:
                            try:
                                _inv_data = []
                                for _, row in _instruct_orders.iterrows():
                                    _inv_data.append({
                                        "shipmentBoxId": int(row["묶음배송번호"]),
                                        "orderId": int(row["주문번호"]),
                                        "vendorItemId": int(row["옵션ID"]) if pd.notna(row["옵션ID"]) else 0,
                                        "deliveryCompanyCode": _sel_company,
                                        "invoiceNumber": _inv_number,
                                    })
                                _inv_result = _mgmt_client.upload_invoice(_inv_data)
                                st.success(f"송장 등록 완료: {len(_inv_data)}건")
                                # DB 상태 업데이트
                                with engine.connect() as conn:
                                    for _inv in _inv_data:
                                        conn.execute(text("""
                                            UPDATE orders SET status = 'DEPARTURE',
                                                   delivery_company_name = :comp,
                                                   invoice_number = :inv,
                                                   updated_at = :now
                                            WHERE account_id = :aid AND shipment_box_id = :sid
                                        """), {
                                            "comp": _delivery_companies[_sel_company],
                                            "inv": _inv_number,
                                            "now": datetime.utcnow().isoformat(),
                                            "aid": _mgmt_account_id,
                                            "sid": _inv["shipmentBoxId"],
                                        })
                                    conn.commit()
                                st.cache_data.clear()
                            except CoupangWingError as e:
                                st.error(f"API 오류: {e}")
                        else:
                            st.error("WING API 클라이언트를 생성할 수 없습니다.")

                st.divider()

                # ── 주문 취소 ──
                st.subheader("주문 취소")
                st.caption("ACCEPT/INSTRUCT 상태의 주문을 취소 요청합니다.")

                _cancelable = query_df(f"""
                    SELECT o.order_id as 주문번호,
                           o.vendor_item_id as 옵션ID,
                           o.seller_product_name as 상품명,
                           o.shipping_count as 수량,
                           o.order_price as 결제금액,
                           o.status as 상태,
                           DATE(o.ordered_at) as 주문일
                    FROM orders o
                    WHERE o.account_id = :aid AND o.status IN ('ACCEPT', 'INSTRUCT')
                    ORDER BY o.ordered_at
                """, {"aid": _mgmt_account_id})

                if _cancelable.empty:
                    st.info("취소 가능한 주문이 없습니다.")
                else:
                    st.dataframe(_cancelable, width="stretch", hide_index=True)

                    _cancel_reasons = {
                        "SOLD_OUT": "재고 소진",
                        "PRICE_ERROR": "가격 오류",
                        "PRODUCT_ERROR": "상품 정보 오류",
                        "OTHER": "기타 사유",
                    }
                    _sel_reason = st.selectbox("취소 사유", list(_cancel_reasons.keys()),
                                                format_func=lambda x: _cancel_reasons[x],
                                                key="cancel_reason")
                    _cancel_detail = st.text_input("상세 사유", value=_cancel_reasons[_sel_reason], key="cancel_detail")

                    st.warning("주문 취소는 되돌릴 수 없습니다. 신중하게 처리하세요.")
                    if st.button("선택 주문 전체 취소", type="secondary", key="btn_cancel_ord"):
                        if _mgmt_client:
                            try:
                                # 주문번호별로 그룹핑하여 취소
                                _cancel_groups = _cancelable.groupby("주문번호")
                                _cancel_count = 0
                                for _oid, _group in _cancel_groups:
                                    _vids = [int(x) for x in _group["옵션ID"].tolist() if pd.notna(x)]
                                    _cnts = [int(x) for x in _group["수량"].tolist()]
                                    if _vids:
                                        _mgmt_client.cancel_order(
                                            order_id=int(_oid),
                                            vendor_item_ids=_vids,
                                            receipt_counts=_cnts,
                                            cancel_reason_category=_sel_reason,
                                            cancel_reason=_cancel_detail,
                                        )
                                        _cancel_count += len(_vids)
                                st.success(f"취소 요청 완료: {_cancel_count}건")
                                # DB 업데이트
                                with engine.connect() as conn:
                                    for _, _cr in _cancelable.iterrows():
                                        conn.execute(text(
                                            "UPDATE orders SET canceled = 1, updated_at = :now WHERE account_id = :aid AND order_id = :oid AND vendor_item_id = :vid"
                                        ), {
                                            "now": datetime.utcnow().isoformat(),
                                            "aid": _mgmt_account_id,
                                            "oid": int(_cr["주문번호"]),
                                            "vid": int(_cr["옵션ID"]) if pd.notna(_cr["옵션ID"]) else 0,
                                        })
                                    conn.commit()
                                st.cache_data.clear()
                            except CoupangWingError as e:
                                st.error(f"API 오류: {e}")
                        else:
                            st.error("WING API 클라이언트를 생성할 수 없습니다.")


st.sidebar.divider()
st.sidebar.caption("v3.8 | 수동 등록 페이지 추가")
