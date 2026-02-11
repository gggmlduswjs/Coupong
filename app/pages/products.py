"""상품 관리 페이지"""
import os
import streamlit as st
import pandas as pd
from datetime import datetime
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from pathlib import Path

from app.dashboard_utils import (
    query_df, run_sql, create_wing_client, fmt_krw, fmt_money_df,
    product_to_upload_data, engine, render_grid,
    CoupangWingError,
)
from app.api.coupang_wing_client import CoupangWingClient
from uploaders.coupang_api_uploader import CoupangAPIUploader, _build_book_notices, _build_book_attributes
from app.constants import (
    WING_ACCOUNT_ENV_MAP, BOOK_CATEGORY_MAP, BOOK_DISCOUNT_RATE,
    COUPANG_FEE_RATE, DEFAULT_SHIPPING_COST, FREE_SHIPPING_THRESHOLD,
    DEFAULT_STOCK,
    determine_customer_shipping_fee,
    determine_delivery_charge_type,
    DISTRIBUTOR_MAP, resolve_distributor, match_publisher_from_text,
)
from config.publishers import get_publisher_info
from app.database import SessionLocal

ROOT = Path(__file__).parent.parent


def render(selected_account, accounts_df, account_names):
    """상품 관리 페이지 렌더링"""
    selected_account_name = selected_account["account_name"] if selected_account is not None else None
    st.title("상품 관리")

    # ── 전체 요약 KPI (단일 쿼리) ──
    _kpi = query_df("""
        SELECT
            COUNT(*) FILTER (WHERE coupang_status = 'active') as active_cnt,
            COUNT(*) FILTER (WHERE coupang_status != 'active') as other_cnt,
            COALESCE(SUM(CASE WHEN coupang_status = 'active' THEN sale_price ELSE 0 END), 0) as total_sale,
            COUNT(*) FILTER (WHERE coupang_status = 'active' AND stock_quantity <= 3) as low_stock_cnt
        FROM listings
    """)
    _pub_cnt = int(query_df("SELECT COUNT(*) as c FROM publishers WHERE is_active = true").iloc[0]['c'])
    _all_active = int(_kpi.iloc[0]['active_cnt'])
    _all_other = int(_kpi.iloc[0]['other_cnt'])
    _total_sale = int(_kpi.iloc[0]['total_sale'])
    _low_stock_cnt = int(_kpi.iloc[0]['low_stock_cnt'])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("판매중", f"{_all_active:,}개")
    c2.metric("기타", f"{_all_other:,}개")
    c3.metric("출판사", f"{_pub_cnt}개")
    c4.metric("총 판매가", f"₩{_total_sale:,}")
    c5.metric("재고 부족", f"{_low_stock_cnt}건", delta=f"{_low_stock_cnt}" if _low_stock_cnt > 0 else None, delta_color="inverse")

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
        WHERE a.is_active = true
        GROUP BY a.id, a.account_name ORDER BY a.account_name
    """)
    if not acct_sum.empty:
        st.dataframe(acct_sum, width="stretch", hide_index=True)

    with st.expander("출판사별 도서 수"):
        pub_df = query_df("""
            SELECT p.name as 출판사, p.margin_rate as "매입율(%)",
                   COUNT(b.id) as 도서수,
                   COALESCE(ROUND(AVG(pr.net_margin)), 0) as "평균마진(원)"
            FROM publishers p
            LEFT JOIN books b ON p.id = b.publisher_id
            LEFT JOIN products pr ON b.id = pr.book_id
            WHERE p.is_active = true GROUP BY p.id HAVING COUNT(b.id) > 0
            ORDER BY COUNT(b.id) DESC LIMIT 10
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
    pm_tab1, pm_tab2, pm_tab3, pm_tab4 = st.tabs(["상품 목록", "가격/재고", "신규 등록", "수동 등록"])


    # ─────────────────────────────────────────────
    # Tab 1: 상품 목록
    # ─────────────────────────────────────────────
    with pm_tab1:
        st.subheader(f"{selected_account_name} 상품 목록")

        _status_counts = query_df("SELECT coupang_status, COUNT(*) as cnt FROM listings WHERE account_id = :acct_id GROUP BY coupang_status", {"acct_id": account_id})
        _sc = dict(zip(_status_counts["coupang_status"], _status_counts["cnt"])) if not _status_counts.empty else {}
        _k1, _k2, _k3, _k4 = st.columns(4)
        _k1.metric("판매중", f"{_sc.get('active', 0):,}건")
        _k2.metric("판매중지", f"{_sc.get('paused', 0):,}건")
        _k3.metric("품절/기타", f"{_sc.get('sold_out', 0) + _sc.get('pending', 0) + _sc.get('rejected', 0):,}건")
        _k4.metric("전체", f"{sum(_sc.values()):,}건")

        col_f1, col_f2, col_f3 = st.columns([1, 2, 1])
        with col_f1:
            _filter_options = ["판매중", "판매중지", "전체", "대기", "품절", "반려"]
            _filter_map = {"판매중": "active", "판매중지": "paused", "대기": "pending", "품절": "sold_out", "반려": "rejected"}
            _filter_label = st.selectbox("상태 필터", _filter_options, key="lst_st")
            status_filter = _filter_map.get(_filter_label, _filter_label)
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
                   l.isbn as "ISBN",
                   COALESCE(l.brand, '') as 출판사,
                   COALESCE(l.coupang_product_id, '-') as "쿠팡ID",
                   COALESCE(l.vendor_item_id, '') as "VID",
                   l.synced_at as 동기화일,
                   pub.supply_rate as _pub_rate,
                   COALESCE(pub2.name, '') as _book_pub
            FROM listings l
            LEFT JOIN publishers pub ON l.brand = pub.name
            LEFT JOIN books b ON l.isbn = b.isbn
            LEFT JOIN publishers pub2 ON b.publisher_id = pub2.id
            WHERE {where_sql}
            ORDER BY l.synced_at DESC NULLS LAST
        """, _lst_params)

        if not listings_df.empty:
            # 브랜드 별칭 → publishers 매핑
            _brand_alias = {
                # 크라운 (55%)
                "크라운출판사": "크라운", "에듀크라운": "크라운", "이찬석": "크라운", "김준한": "크라운",
                "안혜숙": "크라운", "노수정": "크라운",
                # 영진 (55%)
                "영진닷컴": "영진", "영진.com": "영진", "영진com": "영진", "영진.com(영진닷컴)": "영진",
                "영진com 영진닷컴": "영진", "영진정보연구소": "영진", "홍태성": "영진",
                "이노플리아": "영진", "웅진북센": "영진", "일마": "영진",
                "이기적": "영진", "이기적컴활": "영진", "이기적 컴활1급 필기기본서": "영진",
                "이기적 컴퓨터활용능력": "영진", "박윤정": "영진",
                # 매스티안 (55%)
                "매스티안 R&D 센터": "매스티안", "매스티안 편집부": "매스티안",
                "창의사고력 수학 팩토 세트": "매스티안", "미메시스": "매스티안",
                # 소마 (60%)
                "소마셈": "소마", "soma": "소마", "소마출판사": "소마", "소마사고력수학": "소마",
                "소마사고력수학 연구소": "소마", "soma(소마)": "소마",
                # 씨투엠에듀 (60%)
                "씨투엠": "씨투엠에듀", "씨투엠에듀(C2M EDU)": "씨투엠에듀",
                "플라토 세트": "씨투엠에듀", "플라토": "씨투엠에듀", "수학독해 세트": "씨투엠에듀",
                # 해람북스 (40%)
                "해람북스(구 북스홀릭)": "해람북스", "송설북": "해람북스", "해람북스기획팀": "해람북스",
                "해림북스": "해람북스", "방과후교육연구회": "해람북스", "기획팀": "해람북스",
                # 능률교육 (65%)
                "NE능률": "능률교육", "엔이능률": "능률교육", "능률교": "능률교육",
                # 좋은책신사고 (70%)
                "신사고": "좋은책신사고", "홍범준, 신사고수학콘텐츠연구회": "좋은책신사고",
                "홍범준": "좋은책신사고", "홍범준 , 좋은책신사고 편집부": "좋은책신사고",
                "신사고초등콘텐츠연구회": "좋은책신사고", "신사고국어콘텐츠연구회": "좋은책신사고",
                "쎈": "좋은책신사고", "쎈B": "좋은책신사고", "쎈 공통수학": "좋은책신사고",
                "쎈 미적분": "좋은책신사고", "라이트쎈": "좋은책신사고", "일품": "좋은책신사고",
                "우공비": "좋은책신사고",
                # 이지스퍼블리싱 (60%)
                "이지스에듀": "이지스퍼블리싱", "이지스에듀(이지스퍼블리싱)": "이지스퍼블리싱",
                "이지퍼블리싱": "이지스퍼블리싱", "이성용": "이지스퍼블리싱",
                # EBS (73%)
                "EBS한국교육방송공사": "EBS", "한국교육방송공사(EBSi)": "EBS",
                "한국교육방송공사(초등)": "EBS", "EBS교육방송": "EBS",
                "ebs": "EBS", "EBSI": "EBS", "EBS 수능완성": "EBS",
                "기출의 미래": "EBS", "수능특강": "한국교육방송공사",
                # 수경출판사 (65%)
                "수경": "수경출판사", "수경출판사(학습)": "수경출판사", "수경수학콘텐츠연구소": "수경출판사",
                "자이스토리": "수경출판사", "수력충전": "수경출판사",
                # 이퓨처 (60%)
                "이퓨쳐": "이퓨처",
                # 마더텅 (65%)
                "마더텅 편집부": "마더텅", "마덩텅": "마더텅",
                # 지학사 (65%)
                "풍산자": "지학사", "지학사(학습)": "지학사",
                # 비상교육 (65%)
                "비상": "비상교육", "VISANG교육": "비상교육", "비상ESN": "비상교육",
                "비상교육 편집부": "비상교육", "비상교육편집부": "비상교육",
                "오투": "비상교육", "개념+유형": "비상교육", "개념유형": "비상교육",
                "유형만렙": "비상교육", "유형만렙 중학 수학": "비상교육",
                # 렉스미디어 (40%)
                "REXmedia(렉스미디어)": "렉스미디어", "REXmedia 렉스미디어": "렉스미디어",
                "렉스기획팀": "렉스미디어", "렉스디어": "렉스미디어",
                # 길벗 (60%)
                "기사북닷컴": "크라운", "가을책방": "길벗", "길벗출판사": "길벗",
                "환상감자": "길벗", "피피티프로": "길벗", "디렌드라신하": "길벗", "고경희": "길벗",
                "마주현(워킹노마드)": "길벗",
                # 아카데미소프트 (40%)
                "아소미디어(아카데미소프트)": "아카데미소프트", "아소미디어": "아카데미소프트",
                "아카데미소프트사": "아카데미소프트", "아케데미소프트": "아카데미소프트",
                "KIE 기획연구실": "아카데미소프트", "KIE 기획연구실 감수": "아카데미소프트",
                "KIE기획연구실감수": "아카데미소프트", "코딩이지": "아카데미소프트",
                "씨엔씨에듀": "아카데미소프트", "코딩아카데미": "아카데미소프트",
                # 동아 (67%)
                "동아출판": "동아", "동아출판사": "동아", "동아출판편집부": "동아", "동아출판 수학팀": "동아",
                "히어로": "동아",
                # 마린북스 (40%)
                "마린북스 교재개발팀": "마린북스",
                # 렉스미디어닷넷 (40%)
                "류은희": "렉스미디어닷넷", "조준현": "렉스미디어닷넷", "김상민": "렉스미디어닷넷",
                # 이투스북 (65%)
                "이투스에듀 수학개발팀": "이투스북", "고쟁이": "이투스북",
                "수학의 바이블개념ON": "이투스북", "북마트": "이투스북",
                # 에듀원 (62%)
                "에듀원편집부": "에듀원", "에듀원 편집부": "에듀원", "에듀윈": "에듀원",
                "백발백중 100발 100중": "에듀원", "아이와함께": "에듀원", "브랜드없음": "에듀원",
                # 에듀플라자 (62%)
                "(주)에듀플라자": "에듀플라자", "에듀플러스": "에듀플라자",
                "내신콘서트": "에듀플라자",
                # 베스트콜렉션 (62%)
                "베스트교육(베스트콜렉션)": "베스트콜렉션", "베스트컬렉션": "베스트콜렉션",
                "베스트교육": "베스트콜렉션",
                # 디딤돌 (65%)
                "디딤돌교육(학습)": "디딤돌", "디딤돌 편집부": "디딤돌",
                "디딤돌교육 학습": "디딤돌", "디딤돌 초등수학 연구소": "디딤돌",
                # 꿈을담는틀 (65%)
                "꿈을 담는 틀": "꿈을담는틀", "꿈틀": "꿈을담는틀",
                # 미래엔에듀 (65%)
                "미래엔": "미래엔에듀",
                # 사회평론 (60%)
                "Bricks": "사회평론", "BRICKS READING": "사회평론",
                "Bricks Reading Nonfiction": "사회평론", "브릭스": "사회평론",
                # 진학사 (65%)
                "천재교육": "진학사", "천재": "진학사",
                # 시대고시
                "시대고시기획": "시대고시",
                # 기타
                "빅식스": "해람북스", "제이북스": "비상교육",
                "e-future": "이퓨처", "이퓨쳐(e-future)": "이퓨처",
                "에듀왕": "에듀원", "에듀왕(왕수학)": "에듀원",
                "아이베이비북": "해람북스",
                "일품 중등수학 2-2": "좋은책신사고",
                "완자 기출PICK 중학 과학": "비상교육", "완자 기출PICK 중학 사회": "비상교육",
                "개념원리 RPM 알피엠 확률과통계": "개념원리",
                "2026 마더텅 전국연합 학력평가 기출문제집 고1 한국사": "마더텅",
                "Full수록(풀수록) 전국연합 모의고사 국어영역 고1": "비상교육",
                "밀크북(milkbook)": "해람북스",
            }
            _pub_rates = dict(query_df("SELECT name, supply_rate FROM publishers").values.tolist())

            def _resolve_rate(row):
                # 1순위: publishers 직접 매칭
                if pd.notna(row["_pub_rate"]):
                    return float(row["_pub_rate"])
                brand = str(row["출판사"])
                # 2순위: 브랜드 별칭 매핑
                alias = _brand_alias.get(brand)
                if alias and alias in _pub_rates:
                    return float(_pub_rates[alias])
                # 3순위: ISBN → books.publisher_id → publishers.name
                book_pub = row.get("_book_pub")
                if pd.notna(book_pub) and book_pub:
                    if book_pub in _pub_rates:
                        return float(_pub_rates[book_pub])
                    # books 출판사도 별칭 체크
                    alias2 = _brand_alias.get(book_pub)
                    if alias2 and alias2 in _pub_rates:
                        return float(_pub_rates[alias2])
                return 0.65  # 기본값

            listings_df["_supply_rate"] = listings_df.apply(_resolve_rate, axis=1)

            # 순마진 계산: 판매가 - 공급가(정가×공급율) - 수수료(판매가×11%) - 셀러부담배송비
            _lp = listings_df["정가"].fillna(0).astype(int)
            _sp = listings_df["판매가"].fillna(0).astype(int)
            _sr = listings_df["_supply_rate"].astype(float)
            _supply = (_lp * _sr).astype(int)
            _fee = (_sp * COUPANG_FEE_RATE).astype(int)
            _margin = _sp - _supply - _fee
            # 셀러 부담 배송비 = 실제택배비 - 고객부담배송비 (배송비 컬럼 = 고객 부담분)
            _customer_fee = listings_df["배송비"].fillna(0).astype(int)
            _ship_cost = (DEFAULT_SHIPPING_COST - _customer_fee).clip(lower=0)
            listings_df["순마진"] = (_margin - _ship_cost).astype(int)
            listings_df["공급율"] = (_sr * 100).round(0).astype(int).astype(str) + "%"
            listings_df.drop(columns=["_supply_rate", "_pub_rate", "_book_pub"], inplace=True)

            # 상태 한글 변환
            _status_label = {"active": "판매중", "paused": "판매중지", "pending": "대기", "sold_out": "품절", "rejected": "반려"}
            listings_df["상태"] = listings_df["상태"].map(_status_label).fillna(listings_df["상태"])

            # 배송유형 한글 변환 + 배송비 결합
            def _fmt_ship_type(row):
                t = str(row.get("배송유형", "") or "")
                c = int(row.get("배송비", 0) or 0)
                if t == "FREE":
                    return "무료배송"
                if t == "CONDITIONAL_FREE":
                    if c <= 0:
                        return "조건부무료"
                    sr_str = str(row.get("공급율", "65%") or "65%")
                    sr_pct = int(sr_str.replace("%", "").strip() or "65")
                    if sr_pct > 70:
                        thr = "6만"
                    elif sr_pct > 67:
                        thr = "3만"
                    elif sr_pct > 65:
                        thr = "2.5만"
                    else:
                        thr = "2만"
                    return f"조건부({c:,}원/{thr}↑무료)"
                if t == "NOT_FREE":
                    return f"유료({c:,}원)"
                return t or "-"
            listings_df["배송"] = listings_df.apply(_fmt_ship_type, axis=1)

            # 그리드 표시 컬럼 순서
            _grid_cols = ["상품명", "정가", "판매가", "순마진", "공급율", "배송", "재고", "상태", "ISBN", "출판사", "쿠팡ID", "VID", "동기화일"]
            _grid_df = listings_df[_grid_cols]

            _cap_col, _dl_col = st.columns([4, 1])
            _cap_col.caption(f"총 {len(_grid_df):,}건  |  행 클릭 → 하단 상세보기")
            _csv_lst = _grid_df.to_csv(index=False).encode("utf-8-sig")
            _dl_col.download_button("📥 CSV", _csv_lst, f"products_{selected_account_name}.csv", "text/csv", key="dl_lst")

            gb = GridOptionsBuilder.from_dataframe(_grid_df)
            gb.configure_selection(selection_mode="single", use_checkbox=False)
            gb.configure_column("상품명", minWidth=200)
            gb.configure_column("공급율", width=70)
            gb.configure_grid_options(domLayout="normal")
            grid_resp = AgGrid(
                _grid_df,
                gridOptions=gb.build(),
                update_on=["selectionChanged"],
                height=400,
                theme="streamlit",
            )

            selected = grid_resp["selected_rows"]
            if selected is not None and len(selected) > 0:
                sel = selected.iloc[0] if hasattr(selected, "iloc") else pd.Series(selected[0])

                st.divider()
                # 상세 카드
                pc1, pc2 = st.columns([1, 3])
                with pc1:
                    st.markdown('<div style="width:180px;height:240px;background:#f0f0f0;display:flex;align-items:center;justify-content:center;border-radius:8px;color:#999;font-size:48px;">📖</div>', unsafe_allow_html=True)
                with pc2:
                    st.markdown(f"### {sel['상품명']}")
                    dc1, dc2, dc3, dc4, dc5 = st.columns(5)
                    dc1.metric("정가", f"{int(sel['정가'] or 0):,}원")
                    dc2.metric("판매가", f"{int(sel['판매가'] or 0):,}원")
                    dc3.metric("순마진", f"{int(sel.get('순마진', 0) or 0):,}원")
                    dc4.metric("상태", sel["상태"])
                    dc5.metric("쿠팡ID", sel["쿠팡ID"] or "-")
                    st.markdown(f"**ISBN:** `{sel['ISBN'] or '-'}`  |  **VID:** `{sel['VID'] or '-'}`  |  **동기화:** {sel['동기화일'] or '-'}")

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
                                    _wing_client.stop_item_sale(int(_sel_vid), dashboard_override=True)
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
                                            _wing_client.update_original_price(int(_sel_vid), new_orig, dashboard_override=True)
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

        # ── 가격 불일치 목록 (리스팅 실제가 vs 상품 기준가) ──
        st.markdown("#### 가격 불일치")
        _price_diff_df = query_df("""
            SELECT l.id, COALESCE(l.product_name, '(미등록)') as 상품명,
                   p.sale_price as 기준가, l.sale_price as 쿠팡가,
                   (p.sale_price - l.sale_price) as 차이,
                   COALESCE(l.vendor_item_id, '') as "VID",
                   l.isbn as "ISBN"
            FROM listings l
            JOIN products p ON l.product_id = p.id
            WHERE l.account_id = :acct_id
              AND l.coupang_status = 'active'
              AND l.sale_price > 0 AND p.sale_price > 0
              AND l.sale_price != p.sale_price
            ORDER BY ABS(p.sale_price - l.sale_price) DESC
        """, {"acct_id": account_id})

        if not _price_diff_df.empty:
            st.caption(f"{len(_price_diff_df)}건의 가격 불일치 발견")
            _pd_gb = GridOptionsBuilder.from_dataframe(_price_diff_df[["상품명", "기준가", "쿠팡가", "차이", "VID"]])
            _pd_gb.configure_selection(selection_mode="multiple", use_checkbox=True)
            _pd_gb.configure_column("상품명", headerCheckboxSelection=True)
            _pd_gb.configure_grid_options(domLayout="normal")
            _pd_grid = AgGrid(
                _price_diff_df[["상품명", "기준가", "쿠팡가", "차이", "VID"]],
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
                            _pr_target = int(_pr_match.iloc[0]["기준가"]) if not _pr_match.empty else int(_pr.get("기준가", 0))
                            try:
                                _wing_client.update_price(int(_pr_vid), _pr_target, dashboard_override=True)
                                run_sql("UPDATE listings SET sale_price=:sp WHERE account_id=:aid AND vendor_item_id=:vid",
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
                   COALESCE(l.vendor_item_id, '') as "VID",
                   l.isbn as "ISBN"
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
    # Tab 3: 신규 등록
    # ─────────────────────────────────────────────
    with pm_tab3:

        # WING API 활성 계정 로드 (멀티 계정 등록용)
        _wing_accounts = accounts_df[accounts_df["wing_api_enabled"] == 1].to_dict("records")
        _wing_account_cnt = len(_wing_accounts)

        # 전체 ready 상품 + 계정별 등록 현황
        ready = query_df("""
            SELECT p.id as product_id, b.title, pub.name as publisher_name,
                   b.isbn, b.list_price, p.sale_price, p.net_margin,
                   p.shipping_policy, p.supply_rate, b.year,
                   COALESCE(b.sales_point, 0) as sales_point,
                   COALESCE(lc.listed_count, 0) as listed_count,
                   COALESCE(lc.listed_accounts, '') as listed_accounts
            FROM products p
            JOIN books b ON p.book_id = b.id
            LEFT JOIN publishers pub ON b.publisher_id = pub.id
            LEFT JOIN (
                SELECT COALESCE(l.isbn, l.product_name) as match_key,
                       COUNT(DISTINCT l.account_id) as listed_count,
                       STRING_AGG(DISTINCT a.account_name, ',') as listed_accounts
                FROM listings l
                JOIN accounts a ON l.account_id = a.id
                GROUP BY COALESCE(l.isbn, l.product_name)
            ) lc ON lc.match_key = COALESCE(b.isbn, b.title)
            WHERE p.status = 'ready' AND p.can_upload_single = true
            ORDER BY COALESCE(b.sales_point, 0) DESC, p.net_margin DESC
        """)

        # ── 마진/배송비 실시간 재계산 ──
        def _recalc_margin(row):
            """공급률+정가 기준 마진/배송정책 재계산
            - free: 셀러가 배송비 전액 부담 → 순마진 = 마진 - 2,300
            - paid: 고객 부담분만큼 셀러 비용 감소 → 순마진 = 마진 - (2,300 - 고객부담)
            """
            lp = int(row.get("list_price", 0) or 0)
            sr = float(row.get("supply_rate", 0.65) or 0.65)
            margin_rate_pct = int(round(sr * 100))
            sp = int(lp * BOOK_DISCOUNT_RATE)
            supply_cost = int(lp * sr)
            fee = int(sp * COUPANG_FEE_RATE)
            margin = sp - supply_cost - fee
            # 공급률+정가 기반 배송비 결정
            customer_fee = determine_customer_shipping_fee(margin_rate_pct, lp)
            seller_ship = DEFAULT_SHIPPING_COST - customer_fee
            actual_net = margin - seller_ship
            policy = "free" if customer_fee == 0 else "paid"
            return pd.Series({
                "calc_sale": sp, "calc_supply": supply_cost, "calc_fee": fee,
                "calc_margin": margin, "calc_net": actual_net, "calc_ship": policy,
                "calc_customer_fee": customer_fee,
            })

        if not ready.empty:
            _calc = ready.apply(_recalc_margin, axis=1)
            ready = pd.concat([ready, _calc], axis=1)
            ready["ship_changed"] = ready["shipping_policy"] != ready["calc_ship"]

        _all_listed_cnt = len(ready[ready["listed_count"] >= _wing_account_cnt]) if not ready.empty else 0
        _ready_cnt = len(ready) if not ready.empty else 0
        _unlisted_cnt = _ready_cnt - _all_listed_cnt

        k1, k2, k3 = st.columns(3)
        k1.metric("등록 가능", f"{_ready_cnt}건")
        k2.metric("미등록 계정 있음", f"{_unlisted_cnt}건")
        k3.metric(f"전 계정 등록 완료", f"{_all_listed_cnt}건")

        # DB 배송정책 불일치 일괄 반영
        ship_changed_cnt = int(ready["ship_changed"].sum()) if not ready.empty and "ship_changed" in ready.columns else 0
        if not ready.empty and ship_changed_cnt > 0:
            if st.button(f"DB 배송정책 동기화 ({ship_changed_cnt}건)", key="btn_recalc_apply"):
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
                st.success(f"DB 동기화 완료: {_update_cnt}건")
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

        # 필터 (출판사 + 최소 마진 + 등록 완료 제외)
        cf1, cf2, cf3 = st.columns([1, 1, 1])
        with cf1:
            pubs = ["전체"] + sorted(ready["publisher_name"].dropna().unique().tolist())
            pub_f = st.selectbox("출판사", pubs, key="nr_pub")
        with cf2:
            min_m = st.number_input("최소 마진(원)", value=0, step=500, key="nr_mm")
        with cf3:
            hide_full = st.checkbox("전 계정 등록 완료 숨김", value=True, key="nr_hide_full")

        filtered = ready.copy()
        if hide_full:
            filtered = filtered[filtered["listed_count"] < _wing_account_cnt]
        if pub_f != "전체":
            filtered = filtered[filtered["publisher_name"] == pub_f]
        if min_m > 0:
            _margin_col = "calc_net" if "calc_net" in filtered.columns else "net_margin"
            filtered = filtered[filtered[_margin_col] >= min_m]

        if filtered.empty:
            st.info("필터 조건에 맞는 상품이 없습니다.")
            st.stop()

        # ── 일괄 승인/거부 버튼 (그리드 위) ──
        ba1, ba2, ba3 = st.columns([2, 1, 1])
        with ba1:
            st.markdown(f"**조회: {len(filtered)}건**")

        # ── 상품 테이블 (AgGrid) ──
        display = filtered.copy()

        def _ship_display(row):
            """배송비 표시: 무료 / 조건부(X원/Y만↑무료)"""
            cf = int(row.get("calc_customer_fee", 0)) if "calc_customer_fee" in row.index else 0
            policy = row.get("calc_ship", row.get("shipping_policy", "paid"))
            if policy == "free":
                return "무료배송"
            sr_pct = int(round(float(row.get("supply_rate", 0.65) or 0.65) * 100))
            if sr_pct > 70:
                thr = "6만"
            elif sr_pct > 67:
                thr = "3만"
            elif sr_pct > 65:
                thr = "2.5만"
            else:
                thr = "2만"
            fee = cf if cf > 0 else 2300
            return f"조건부({fee:,}원/{thr}↑무료)"
        display["배송"] = display.apply(_ship_display, axis=1)
        display["공급율"] = (display["supply_rate"] * 100).round(0).astype(int).astype(str) + "%" if "supply_rate" in display.columns else ""
        display["순마진"] = display["calc_net"].astype(int) if "calc_net" in display.columns else display["net_margin"].astype(int)
        # 등록 현황: "0/5" 또는 "2/5 (007-book,007-ez)"
        def _fmt_listed(row):
            cnt = int(row["listed_count"])
            accs = str(row.get("listed_accounts", "") or "")
            if cnt == 0 or not accs:
                return f"0/{_wing_account_cnt}"
            return f"{cnt}/{_wing_account_cnt} ({accs})"
        display["등록"] = display.apply(_fmt_listed, axis=1)

        display["판매지수"] = display["sales_point"].astype(int) if "sales_point" in display.columns else 0
        nr_grid_df = display[["title", "publisher_name", "list_price", "sale_price", "순마진", "판매지수", "공급율", "배송", "등록", "isbn", "year"]].rename(columns={
            "title": "제목", "publisher_name": "출판사", "isbn": "ISBN",
            "list_price": "정가", "sale_price": "판매가", "year": "연도",
        })
        nr_gb = GridOptionsBuilder.from_dataframe(nr_grid_df)
        nr_gb.configure_selection(selection_mode="multiple", use_checkbox=True)
        nr_gb.configure_column("제목", headerCheckboxSelection=True, minWidth=250)
        nr_gb.configure_column("판매지수", width=80, sort="desc")
        nr_gb.configure_column("공급율", width=70)
        nr_gb.configure_column("배송", width=100)
        nr_gb.configure_column("등록", minWidth=150)
        nr_gb.configure_grid_options(domLayout="normal", suppressRowClickSelection=True)
        _nr_grid_ver = st.session_state.get("nr_grid_ver", 0)
        nr_grid = AgGrid(
            nr_grid_df,
            gridOptions=nr_gb.build(),
            update_on=["selectionChanged", "cellClicked"],
            height=400,
            theme="streamlit",
            key=f"nr_aggrid_{_nr_grid_ver}",
        )

        # ── 체크박스 선택 → 등록용 (session_state 보존) ──
        nr_selected = nr_grid["selected_rows"]
        if nr_selected is not None:
            _sel_df = nr_selected if isinstance(nr_selected, pd.DataFrame) else pd.DataFrame(nr_selected)
            if len(_sel_df) > 0:
                st.session_state["nr_sel_titles"] = _sel_df["제목"].tolist()
            else:
                st.session_state["nr_sel_titles"] = []
        _persisted_titles = st.session_state.get("nr_sel_titles", [])
        sel_idx = [i for i, t in enumerate(display["title"]) if t in _persisted_titles]
        sel_cnt = len(sel_idx)

        # ── 행 클릭 → 상세보기용 (체크박스와 독립) ──
        _event = nr_grid.get("event_data")
        if _event and isinstance(_event, dict):
            _row_data = _event.get("data") or _event.get("rowData")
            if _row_data and isinstance(_row_data, dict) and _row_data.get("제목"):
                st.session_state["nr_detail_title"] = _row_data["제목"]

        st.markdown(f"**선택: {sel_cnt}건**")
        ap1, ap2 = st.columns([1, 5])
        with ap1:
            if st.button("선택 초기화", disabled=(sel_cnt == 0), key="btn_nr_clear"):
                st.session_state["nr_sel_titles"] = []
                st.session_state["nr_grid_ver"] = _nr_grid_ver + 1
                st.rerun()

        # ── 행 클릭 → 상세 보기 ──
        _detail_title = st.session_state.get("nr_detail_title")
        if _detail_title:
            _match = display[display["title"] == _detail_title]
            if not _match.empty:
                nr_sel = _match.iloc[0]
                book_id_row = query_df("SELECT id FROM books WHERE isbn = :isbn LIMIT 1", {"isbn": nr_sel["isbn"]}) if nr_sel["isbn"] else pd.DataFrame()

                st.divider()
                pv1, pv2 = st.columns([1, 3])
                with pv1:
                    st.markdown('<div style="width:150px;height:200px;background:#f0f0f0;display:flex;align-items:center;justify-content:center;border-radius:8px;color:#999;font-size:40px;">📖</div>', unsafe_allow_html=True)
                with pv2:
                    st.markdown(f"**{nr_sel['title']}**")
                    st.markdown(f"{nr_sel['publisher_name']} | ISBN: `{nr_sel['isbn']}`")
                    _detail_net = int(nr_sel.get('calc_net', nr_sel.get('net_margin', 0)) or 0)
                    st.markdown(f"정가 {int(nr_sel['list_price']):,}원 → 판매가 {int(nr_sel['sale_price']):,}원 | 순마진 **{_detail_net:,}원**")
                    # 등록된 계정 표시
                    _listed_accs = str(nr_sel.get("listed_accounts", "") or "")
                    _listed_cnt = int(nr_sel.get("listed_count", 0))
                    if _listed_cnt > 0 and _listed_accs:
                        st.markdown(f"등록 계정: **{_listed_accs}** ({_listed_cnt}/{_wing_account_cnt})")
                    else:
                        st.markdown(f"등록 계정: 없음 (0/{_wing_account_cnt})")

                with st.expander("수정 / 삭제"):
                    bid = int(book_id_row.iloc[0]["id"]) if not book_id_row.empty else None
                    pid = int(nr_sel["product_id"])
                    if bid:
                        with st.form("nr_edit_form"):
                            # 1행: 제목
                            ed_title = st.text_input("제목", value=nr_sel["title"] or "")
                            # 2행: 판매가 / 정가 / 배송
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
                                    # books 테이블 업데이트
                                    run_sql(
                                        "UPDATE books SET title=:t, list_price=:lp WHERE id=:id",
                                        {"t": ed_title, "lp": ed_price, "id": bid}
                                    )
                                    # products 테이블 업데이트 (마진 재계산)
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
                                st.session_state.pop("nr_detail_title", None)
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"삭제 실패: {e}")

        st.divider()

        # ── 등록 매트릭스 프리뷰 + 일괄 등록 ──
        # 모든 선택된 상품은 등록 가능 (registration_status 삭제됨)
        _approved_sel_idx = sel_idx
        _approved_cnt = len(_approved_sel_idx)
        _unapproved_cnt = 0

        st.subheader("일괄 등록")

        if not _wing_accounts:
            st.warning("WING API가 활성화된 계정이 없습니다.")
        else:
            # 상품 × 계정 매트릭스 (등록됨=✓ 텍스트, 미등록=체크박스)
            _selected_pairs = {}  # {mi: [acc_objs]}
            _total_missing = 0
            _registered_map = {}

            if _approved_cnt > 0:
                _acc_cnt = len(_wing_accounts)
                # 헤더
                _hdr = st.columns([3] + [1] * _acc_cnt)
                _hdr[0].markdown("**상품명**")
                for _ai, _acc in enumerate(_wing_accounts):
                    _hdr[_ai + 1].markdown(f"**{_acc['account_name']}**")

                for _mi, idx in enumerate(_approved_sel_idx):
                    row = display.iloc[idx]
                    _name = str(row.get("title", ""))[:30]
                    _listed_str = str(row.get("listed_accounts", "") or "")
                    _listed = set(a.strip() for a in _listed_str.split(",") if a.strip())

                    _cols = st.columns([3] + [1] * _acc_cnt)
                    _cols[0].write(_name)

                    _sel_accs = []
                    _reg_row = {}
                    for _ai, _acc in enumerate(_wing_accounts):
                        _aname = _acc["account_name"]
                        _is_reg = _aname in _listed
                        _reg_row[_aname] = _is_reg
                        if _is_reg:
                            _cols[_ai + 1].markdown("✅")
                        else:
                            _chk = _cols[_ai + 1].checkbox(
                                _aname, value=True,
                                key=f"nr_reg_{_mi}_{_aname}",
                                label_visibility="collapsed",
                            )
                            if _chk:
                                _sel_accs.append(_acc)
                                _total_missing += 1
                    _selected_pairs[_mi] = _sel_accs
                    _registered_map[_mi] = _reg_row

                st.caption("✅ = 이미 등록됨 · ☑ = 신규 등록 예정 · 체크 해제 = 등록 제외")

            # 요약 + 버튼
            _summary_parts = [f"등록 예정 **{_total_missing}건**"]
            if _unapproved_cnt > 0:
                _summary_parts.append(f"미승인 {_unapproved_cnt}건 제외")
            cb1, cb2, cb3 = st.columns([3, 1, 3])
            with cb1:
                st.markdown(" | ".join(_summary_parts))
            with cb2:
                dry = st.checkbox("Dry Run", value=False, key="dry", help="체크 시 실제 등록 안 하고 확인만")
            with cb3:
                btn = st.button(
                    f"{'테스트' if dry else '선택 항목 등록'} ({_total_missing}건)",
                    type="primary", disabled=(_total_missing == 0),
                )

            if btn and _approved_cnt > 0 and _total_missing > 0:
                progress = st.progress(0, text="준비 중...")
                result_box = st.container()
                ok_list, fail_list = [], []
                _done = 0

                for _mi, idx in enumerate(_approved_sel_idx):
                    row = display.iloc[idx]
                    pd_data = product_to_upload_data(row)
                    name = pd_data["product_name"]
                    _row_listed = set(a.strip() for a in str(row.get("listed_accounts", "") or "").split(",") if a.strip())

                    for _acc in _selected_pairs.get(_mi, []):
                        _acc_name = _acc["account_name"]

                        _done += 1
                        progress.progress(min(_done / _total_missing, 1.0), text=f"[{_done}/{_total_missing}] {_acc_name} — {name[:25]}...")

                        _out_code = str(_acc.get("outbound_shipping_code", ""))
                        _ret_code = str(_acc.get("return_center_code", ""))

                        if not _out_code or not _ret_code:
                            fail_list.append({"계정": _acc_name, "제목": name[:35], "결과": "출고지/반품지 미설정"})
                            continue

                        _client = create_wing_client(_acc)
                        if _client is None:
                            fail_list.append({"계정": _acc_name, "제목": name[:35], "결과": "API 키 미설정"})
                            continue

                        _uploader = CoupangAPIUploader(_client, vendor_user_id=_acc_name)

                        if dry:
                            try:
                                _uploader.build_product_payload(pd_data, _out_code, _ret_code)
                                ok_list.append({"계정": _acc_name, "제목": name[:35], "ISBN": pd_data["isbn"], "결과": "OK"})
                            except Exception as e:
                                fail_list.append({"계정": _acc_name, "제목": name[:35], "결과": str(e)[:80]})
                        else:
                            res = _uploader.upload_product(pd_data, _out_code, _ret_code, dashboard_override=True)
                            if res["success"]:
                                sid = res["seller_product_id"]
                                ok_list.append({"계정": _acc_name, "제목": name[:35], "쿠팡ID": sid, "결과": "성공"})
                                # 배송비 계산
                                _mr = int(pd_data.get("margin_rate", 65))
                                _lp = int(pd_data.get("original_price", 0))
                                _dct, _dc, _fsoa = determine_delivery_charge_type(_mr, _lp)
                                try:
                                    with engine.connect() as conn:
                                        conn.execute(text("""
                                            INSERT INTO listings
                                            (account_id, product_id, isbn, coupang_product_id,
                                             coupang_status, sale_price, original_price, product_name,
                                             stock_quantity, delivery_charge_type, delivery_charge, free_ship_over_amount,
                                             synced_at)
                                            VALUES (:aid, :pid, :isbn, :cid, 'active', :sp, :op, :pn,
                                                    :stock, :dct, :dc, :fsoa, :now)
                                            ON CONFLICT DO NOTHING
                                        """), {
                                            "aid": int(_acc["id"]), "pid": int(row["product_id"]),
                                            "isbn": pd_data["isbn"], "cid": sid,
                                            "sp": pd_data["sale_price"], "op": pd_data["original_price"],
                                            "pn": name,
                                            "stock": DEFAULT_STOCK, "dct": _dct, "dc": _dc, "fsoa": _fsoa,
                                            "now": datetime.now().isoformat(),
                                        })
                                        # 이번 등록 반영 → 전 계정 완료 여부 체크
                                        _row_listed.add(_acc_name)
                                        if len(_row_listed) >= _wing_account_cnt:
                                            conn.execute(text(
                                                "UPDATE products SET status = 'uploaded' WHERE id = :id"
                                            ), {"id": int(row["product_id"])})
                                        conn.commit()
                                except Exception as db_e:
                                    logger.warning(f"DB 저장 실패 ({_acc_name}): {db_e}")
                            else:
                                fail_list.append({"계정": _acc_name, "제목": name[:35], "결과": res["message"][:80]})

                progress.progress(1.0, text="완료!")
                with result_box:
                    if ok_list:
                        st.success(f"성공: {len(ok_list)}건")
                        st.dataframe(pd.DataFrame(ok_list), width="stretch", hide_index=True)
                    if fail_list:
                        st.error(f"실패: {len(fail_list)}건")
                        st.dataframe(pd.DataFrame(fail_list), width="stretch", hide_index=True)
                query_df.clear()
                st.session_state.pop("nr_sel_titles", None)
                if ok_list and not dry:
                    import time
                    time.sleep(1)
                    st.cache_data.clear()
                    st.rerun()


    # ═══════════════════════════════════════

    # ─────────────────────────────────────────────
    # Tab 4: 수동 등록
    # ─────────────────────────────────────────────
    with pm_tab4:
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
                    "SELECT b.title, pub.name as publisher_name, b.list_price FROM books b LEFT JOIN publishers pub ON b.publisher_id = pub.id WHERE b.isbn = :isbn LIMIT 1",
                    {"isbn": _isbn_input}
                )
                if not _db_book.empty:
                    _row = _db_book.iloc[0]
                    st.session_state["m_title"] = _row["title"] or ""
                    st.session_state["m_author"] = ""
                    st.session_state["m_publisher"] = _row["publisher_name"] or ""
                    st.session_state["m_list_price"] = int(_row["list_price"]) if pd.notna(_row["list_price"]) else 0
                    st.session_state["m_image"] = ""
                    st.session_state["m_desc"] = ""
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
                                st.session_state["m_image"] = ""  # image_url deleted from Book model
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
                # 출판사 정보로 조건부 무료배송 기준 결정
                _pub_info = get_publisher_info(_m_publisher) if _m_publisher else None
                _pub_margin = _pub_info["margin"] if _pub_info else 65
                if _pub_margin > 70:
                    _cond_thr_label = "6만"
                elif _pub_margin > 67:
                    _cond_thr_label = "3만"
                elif _pub_margin > 65:
                    _cond_thr_label = "2.5만"
                else:
                    _cond_thr_label = "2만"
                _ship_options = [
                    "무료배송",
                    f"조건부(1,000원/{_cond_thr_label}↑무료)",
                    f"조건부(2,000원/{_cond_thr_label}↑무료)",
                    f"조건부(2,300원/{_cond_thr_label}↑무료)",
                ]
                _m_shipping = st.radio(
                    "배송비", _ship_options,
                    index=0, key="m_form_shipping", horizontal=True,
                )

            # 마진 미리보기
            if _m_sale_price > 0 and _m_list_price > 0:
                _commission_rate = 0.11
                _commission = int(_m_sale_price * _commission_rate)
                # 고객 부담 배송비에 따른 셀러 부담 배송비 계산 (라벨에서 금액 추출)
                if _m_shipping == "무료배송":
                    _customer_ship = 0
                elif "1,000원" in _m_shipping:
                    _customer_ship = 1000
                elif "2,000원" in _m_shipping:
                    _customer_ship = 2000
                else:
                    _customer_ship = 2300
                _shipping_cost = DEFAULT_SHIPPING_COST - _customer_ship  # 셀러 부담
                _margin = _m_sale_price - _m_list_price - _commission - _shipping_cost
                _margin_rate = (_margin / _m_sale_price * 100) if _m_sale_price > 0 else 0

                st.markdown("---")
                _mg1, _mg2, _mg3, _mg4 = st.columns(4)
                with _mg1:
                    st.metric("쿠팡 수수료 (11%)", f"₩{_commission:,}")
                with _mg2:
                    _ship_label = f"₩{_shipping_cost:,}" + (f" (고객 ₩{_customer_ship:,})" if _customer_ship > 0 else " (셀러 전액)")
                    st.metric("셀러 배송 부담", _ship_label)
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
                "margin_rate": _pub_margin,
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
                            _product_data, _out_code, _ret_code, dashboard_override=True,
                        )
                        if _res["success"]:
                            _sid = _res["seller_product_id"]
                            _ok_list.append({"계정": _acc_name, "쿠팡ID": _sid, "결과": "성공"})
                            # 배송비 계산
                            _m_dct, _m_dc, _m_fsoa = determine_delivery_charge_type(_pub_margin, _m_list_price)
                            try:
                                with engine.connect() as conn:
                                    conn.execute(text("""
                                        INSERT INTO listings
                                        (account_id, isbn, coupang_product_id,
                                         coupang_status, sale_price, original_price, product_name,
                                         stock_quantity, delivery_charge_type, delivery_charge, free_ship_over_amount,
                                         synced_at)
                                        VALUES (:aid, :isbn, :cid, 'active', :sp, :op, :pn,
                                                :stock, :dct, :dc, :fsoa, :now)
                                        ON CONFLICT DO NOTHING
                                    """), {
                                        "aid": int(_acc["id"]),
                                        "isbn": _m_isbn,
                                        "cid": _sid,
                                        "sp": _m_sale_price,
                                        "op": _m_list_price,
                                        "pn": _m_title,
                                        "stock": DEFAULT_STOCK, "dct": _m_dct, "dc": _m_dc, "fsoa": _m_fsoa,
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


    # ════════════════════════════════════════
    # 분석
    # ════════════════════════════════════════
