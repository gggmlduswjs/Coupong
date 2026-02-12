"""상품 관리 — Tab 1: 상품 목록"""
import logging
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder

from app.dashboard_utils import (
    query_df, query_df_cached, run_sql, CoupangWingError,
)
from app.constants import COUPANG_FEE_RATE, DEFAULT_SHIPPING_COST

logger = logging.getLogger(__name__)


def render_tab_list(account_id, selected_account, accounts_df, _wing_client):
    """Tab 1: 상품 목록 렌더링"""
    selected_account_name = selected_account["account_name"] if selected_account is not None else None
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
        where_parts.append("(l.product_name LIKE :sq OR l.isbn LIKE :sq OR CAST(l.coupang_product_id AS TEXT) LIKE :sq)")
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
               COALESCE(CAST(l.coupang_product_id AS TEXT), '-') as "쿠팡ID",
               COALESCE(CAST(l.vendor_item_id AS TEXT), '') as "VID",
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
        _pub_rates = dict(query_df_cached("SELECT name, supply_rate FROM publishers").values.tolist())

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
