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
from uploaders.coupang_api_uploader import CoupangAPIUploader
from app.constants import WING_ACCOUNT_ENV_MAP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# ─── DB ───
DB_PATH = ROOT / "coupang_auto.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

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
page = st.sidebar.radio("메뉴", ["매출", "정산", "상품 관리", "신규 등록"])

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

    # ── 전체 요약 ──
    _all_active = int(query_df("SELECT COUNT(*) as c FROM listings WHERE coupang_status = 'active'").iloc[0]['c'])
    _all_other = int(query_df("SELECT COUNT(*) as c FROM listings WHERE coupang_status != 'active'").iloc[0]['c'])
    _pub_cnt = int(query_df("SELECT COUNT(*) as c FROM publishers WHERE is_active = 1").iloc[0]['c'])
    _total_sale = int(query_df("SELECT COALESCE(SUM(sale_price), 0) as s FROM listings WHERE coupang_status = 'active'").iloc[0]['s'])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("판매중", f"{_all_active:,}개")
    c2.metric("기타 (대기/반려/품절)", f"{_all_other:,}개")
    c3.metric("활성 출판사", f"{_pub_cnt}개")
    c4.metric("총 판매가 합계", f"₩{_total_sale:,}")

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
            st.dataframe(pub_df, width="stretch", hide_index=True)

    st.divider()

    # ── 계정별 상세 ──
    if selected_account is None:
        st.info("왼쪽에서 계정을 선택하면 상세 조회할 수 있습니다.")
        st.stop()

    account_id = int(selected_account["id"])
    st.subheader(f"{selected_account_name} 상품 목록")

    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        status_filter = st.selectbox("상태 필터", ["전체", "active", "pending", "rejected", "sold_out"], key="lst_st")
    with col_f2:
        search_q = st.text_input("검색 (상품명 / ISBN)", key="lst_search")

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
        SELECT COALESCE(l.product_name, b.title, '(미등록)') as 상품명,
               l.sale_price as 판매가,
               l.coupang_status as 상태,
               l.isbn as ISBN,
               COALESCE(l.coupang_product_id, '-') as 쿠팡ID,
               l.uploaded_at as 등록일
        FROM listings l
        LEFT JOIN products p ON l.product_id = p.id
        LEFT JOIN books b ON p.book_id = b.id
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
                dc1, dc2, dc3 = st.columns(3)
                dc1.metric("판매가", f"{int(sel['판매가'] or 0):,}원")
                dc2.metric("상태", sel["상태"])
                dc3.metric("쿠팡ID", sel["쿠팡ID"] or "-")
                st.markdown(f"**ISBN:** `{sel['ISBN'] or '-'}`  |  **등록일:** {sel['등록일'] or '-'}")
                if description:
                    with st.expander("상품 설명"):
                        st.markdown(description[:500])

            # 수정 폼
            with st.expander("수정"):
                sel_title = sel["상품명"] or ""
                lid_row = query_df("""
                    SELECT l.id FROM listings l
                    WHERE l.account_id = :acct_id
                      AND COALESCE(l.product_name, '') = :title
                      AND COALESCE(l.isbn, '') = :isbn
                    LIMIT 1
                """, {"acct_id": account_id, "title": sel_title, "isbn": sel["ISBN"] or ""})
                if not lid_row.empty:
                    lid = int(lid_row.iloc[0]["id"])
                    with st.form("lst_edit_form"):
                        new_name = st.text_input("상품명", value=sel["상품명"] or "")
                        le1, le2 = st.columns(2)
                        with le1:
                            new_sp = st.number_input("판매가", value=int(sel["판매가"] or 0), step=100)
                        with le2:
                            status_opts = ["active", "pending", "rejected", "sold_out"]
                            cur_idx = status_opts.index(sel["상태"]) if sel["상태"] in status_opts else 0
                            new_status = st.selectbox("상태", status_opts, index=cur_idx)
                        if st.form_submit_button("저장", type="primary"):
                            try:
                                run_sql("UPDATE listings SET product_name=:name, sale_price=:sp, coupang_status=:st WHERE id=:id",
                                        {"name": new_name, "sp": new_sp, "st": new_status, "id": lid})
                                st.success("저장 완료")
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"저장 실패: {e}")
    else:
        st.info("조건에 맞는 상품이 없습니다.")


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

    # 등록 가능 상품
    ready = query_df(f"""
        SELECT p.id as product_id, b.title, b.author, b.publisher_name,
               b.isbn, b.image_url, b.list_price, p.sale_price, p.net_margin,
               p.shipping_policy, b.year, b.description
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
        ORDER BY p.net_margin DESC
    """)

    total_registered = query_df(f"SELECT COUNT(*) as c FROM listings WHERE account_id = {account_id}")
    reg_cnt = int(total_registered.iloc[0]["c"]) if not total_registered.empty else 0

    c1, c2 = st.columns(2)
    c1.metric("등록 가능", f"{len(ready)}건")
    c2.metric("이미 등록됨", f"{reg_cnt:,}건")

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

    # 필터
    cf1, cf2 = st.columns(2)
    with cf1:
        pubs = ["전체"] + sorted(ready["publisher_name"].dropna().unique().tolist())
        pub_f = st.selectbox("출판사", pubs, key="nr_pub")
    with cf2:
        min_m = st.number_input("최소 마진(원)", value=0, step=500, key="nr_mm")

    filtered = ready.copy()
    if pub_f != "전체":
        filtered = filtered[filtered["publisher_name"] == pub_f]
    if min_m > 0:
        filtered = filtered[filtered["net_margin"] >= min_m]

    if filtered.empty:
        st.info("필터 조건에 맞는 상품이 없습니다.")
        st.stop()

    # ── 상품 테이블 (AgGrid: 체크박스 = 등록, 행 클릭 = 상세) ──
    display = filtered.head(100).copy()

    nr_grid_df = display[["title", "publisher_name", "sale_price", "net_margin", "year"]].rename(columns={
        "title": "제목", "publisher_name": "출판사",
        "sale_price": "판매가", "net_margin": "순마진", "year": "연도",
    })
    nr_gb = GridOptionsBuilder.from_dataframe(nr_grid_df)
    nr_gb.configure_selection(selection_mode="multiple", use_checkbox=True)
    nr_gb.configure_column("제목", headerCheckboxSelection=True)
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
                st.markdown(f"{author or ''} | {nr_sel['publisher_name']} | ISBN: `{nr_sel['isbn']}`")
                st.markdown(f"정가 {int(nr_sel['list_price']):,}원 → 판매가 {int(nr_sel['sale_price']):,}원 | 순마진 **{int(nr_sel['net_margin']):,}원**")

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
                                nm = ed_sale - ed_price * 0.35 - int(ed_sale * 0.11)
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

    # 등록 버튼
    cb1, cb2, cb3 = st.columns([2, 1, 3])
    with cb1:
        st.markdown(f"**선택: {sel_cnt}건**")
    with cb2:
        dry = st.checkbox("Dry Run", value=True, key="dry", help="실제 등록 안 하고 확인만")
    with cb3:
        btn = st.button(
            f"{'테스트' if dry else '쿠팡에 등록'} ({sel_cnt}건)",
            type="primary", disabled=(sel_cnt == 0),
        )

    if btn and sel_cnt > 0:
        client = create_wing_client(selected_account)
        if client is None:
            st.error("API 키 미설정")
            st.stop()

        uploader = CoupangAPIUploader(client, vendor_user_id=selected_account_name)
        progress = st.progress(0, text="준비 중...")
        result_box = st.container()
        ok_list, fail_list = [], []

        for i, idx in enumerate(sel_idx):
            row = display.iloc[idx]
            pd_data = product_to_upload_data(row)
            name = pd_data["product_name"]
            progress.progress((i+1)/sel_cnt, text=f"[{i+1}/{sel_cnt}] {name[:30]}...")

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
            st.dataframe(best, width="stretch", hide_index=True)
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
                st.dataframe(ad, width="stretch", hide_index=True)
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
                st.dataframe(acct_rev, width="stretch", hide_index=True)
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
                    st.dataframe(prod_detail, width="stretch", hide_index=True)
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
                    st.dataframe(pub_rev, width="stretch", hide_index=True)
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
                    st.dataframe(monthly, width="stretch", hide_index=True)
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
                        st.dataframe(refund_list, width="stretch", hide_index=True)
                else:
                    st.info("환불 내역이 없습니다.")


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

    # ── KPI ──
    _s_kpi = query_df(f"""
        SELECT
            COALESCE(SUM(s.total_sale), 0) as total_sale,
            COALESCE(SUM(s.settlement_target_amount), 0) as target_amount,
            COALESCE(SUM(s.final_amount), 0) as final_amount,
            COALESCE(SUM(s.service_fee), 0) as service_fee
        FROM settlement_history s
        WHERE 1=1 {_s_acct_where} {_s_month_where}
    """)

    if _s_kpi.empty or int(_s_kpi.iloc[0]["total_sale"]) == 0:
        st.info("해당 기간 정산 데이터가 없습니다. '정산 동기화' 버튼을 눌러주세요.")
        st.stop()

    _sk = _s_kpi.iloc[0]
    _s_total_sale = int(_sk["total_sale"])
    _s_target = int(_sk["target_amount"])
    _s_final = int(_sk["final_amount"])
    _s_fee = int(_sk["service_fee"])
    _s_fee_rate = round(abs(_s_fee) / _s_total_sale * 100, 1) if _s_total_sale > 0 else 0

    sk1, sk2, sk3, sk4 = st.columns(4)
    sk1.metric("총판매액", _fmt_krw_s(_s_total_sale))
    sk2.metric("정산대상액", _fmt_krw_s(_s_target))
    sk3.metric("최종지급액", _fmt_krw_s(_s_final))
    sk4.metric("수수료율", f"{_s_fee_rate}%")

    st.caption(f"선택 기간: {settle_months[-1]} ~ {settle_months[0]}  |  수수료 합계: {_fmt_krw_s(abs(_s_fee))}")

    # ── 월별 추이 차트 ──
    _s_monthly = query_df(f"""
        SELECT s.year_month as 월,
            SUM(s.total_sale) as 총판매액,
            SUM(s.settlement_target_amount) as 정산대상액,
            SUM(s.final_amount) as 최종지급액
        FROM settlement_history s
        WHERE 1=1 {_s_acct_where} {_s_month_where}
        GROUP BY s.year_month ORDER BY s.year_month
    """)
    if not _s_monthly.empty:
        st.bar_chart(_s_monthly.set_index("월")[["총판매액", "정산대상액", "최종지급액"]])

    st.divider()

    # ── 하단 탭 3개 ──
    stab1, stab2, stab3 = st.tabs(["📊 계정별 비교", "📅 월별 상세", "📋 정산 상태"])

    with stab1:
        _s_acct_cmp = query_df(f"""
            SELECT a.account_name as 계정,
                SUM(s.total_sale) as 총판매액,
                SUM(s.service_fee) as 수수료,
                SUM(s.settlement_target_amount) as 정산대상액,
                SUM(s.final_amount) as 최종지급액,
                ROUND(ABS(SUM(s.service_fee)) * 100.0 / NULLIF(SUM(s.total_sale), 0), 1) as '수수료율(%)'
            FROM settlement_history s
            JOIN accounts a ON s.account_id = a.id
            WHERE 1=1 {_s_month_where}
            GROUP BY s.account_id ORDER BY 총판매액 DESC
        """)
        if not _s_acct_cmp.empty:
            _sc_chart, _sc_pie = st.columns([3, 2])
            with _sc_chart:
                st.bar_chart(_s_acct_cmp.set_index("계정")["최종지급액"])
            with _sc_pie:
                import plotly.express as px
                _s_pie = _s_acct_cmp[_s_acct_cmp["총판매액"] > 0]
                if not _s_pie.empty:
                    fig = px.pie(_s_pie, values="총판매액", names="계정", title="매출 비중",
                                 hole=0.4, color_discrete_sequence=px.colors.qualitative.Set2)
                    fig.update_layout(margin=dict(t=40, b=10, l=10, r=10), height=300, showlegend=True)
                    st.plotly_chart(fig, width="stretch")
            st.dataframe(_s_acct_cmp, width="stretch", hide_index=True)
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
            st.dataframe(_s_detail, width="stretch", hide_index=True)
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

            st.dataframe(_s_status, width="stretch", hide_index=True)

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
                    st.dataframe(_subj_detail, width="stretch", hide_index=True)
        else:
            st.info("정산 상태 데이터가 없습니다.")


st.sidebar.divider()
st.sidebar.caption("v3.3 | 정산 내역 조회 추가")
