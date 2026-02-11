"""
분석 페이지 (매출 / 정산)
=========================
dashboard.py에서 분리한 분석 탭.
"""

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import text

from app.dashboard_utils import (
    query_df,
    run_sql,
    create_wing_client,
    fmt_krw,
    fmt_money_df,
    render_grid,
    engine,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent


def render(selected_account, accounts_df, account_names):
    """분석 페이지 렌더링 (매출 + 정산 탭)"""

    st.title("분석")

    _an_tab1, _an_tab2 = st.tabs(["매출", "정산"])

    with _an_tab1:

        _fmt_krw = fmt_krw

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
        date_to = date.today()
        date_from = date_to - timedelta(days=days_back)
        date_from_str = date_from.isoformat()
        date_to_str = date_to.isoformat()
        prev_date_to = date_from - timedelta(days=1)
        prev_date_from = prev_date_to - timedelta(days=days_back)
        prev_from_str = prev_date_from.isoformat()
        prev_to_str = prev_date_to.isoformat()


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
            GROUP BY r.vendor_item_id, r.product_name ORDER BY qty DESC LIMIT 1
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
                GROUP BY r.account_id, a.account_name ORDER BY rev DESC LIMIT 1
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
                GROUP BY r.vendor_item_id, r.product_name ORDER BY 주문수 DESC LIMIT 15
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
                        ) as "정산율(%)"
                    FROM revenue_history r
                    WHERE r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}' {acct_where}
                    GROUP BY r.vendor_item_id, r.product_name
                    HAVING COUNT(*) >= 2
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
                        ) as "정산율(%)"
                    FROM revenue_history r
                    JOIN accounts a ON r.account_id = a.id
                    WHERE r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
                    GROUP BY r.account_id, a.account_name ORDER BY 매출 DESC
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
                            ) as "정산율(%)"
                        FROM revenue_history r
                        WHERE r.account_id = {_acct_id}
                          AND r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
                        GROUP BY r.vendor_item_id, r.product_name ORDER BY 매출 DESC LIMIT 20
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
                            TO_CHAR(r.recognition_date::date, 'YYYY-MM') as 월,
                            SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as 매출,
                            SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END) as 정산,
                            SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as 주문수
                        FROM revenue_history r
                        WHERE r.account_id = {_acct_id}
                          AND r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
                        GROUP BY TO_CHAR(r.recognition_date::date, 'YYYY-MM') ORDER BY 월
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
                            GROUP BY r.vendor_item_id, r.product_name ORDER BY 환불수량 DESC LIMIT 10
                        """)
                        if not refund_list.empty:
                            st.dataframe(fmt_money_df(refund_list), width="stretch", hide_index=True)
                    else:
                        st.info("환불 내역이 없습니다.")



    with _an_tab2:

        _fmt_krw_s = fmt_krw

        # ── 상단 컨트롤 ──
        from scripts.sync_settlement import SettlementSync

        # 최근 12개월 목록 생성
        _s_today = date.today()
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
                    ROUND(SUM(s.final_amount) * 100.0 / NULLIF(SUM(s.total_sale), 0), 1) as "수취율(%)"
                FROM settlement_history s
                JOIN accounts a ON s.account_id = a.id
                WHERE s.settlement_type IN ('WEEKLY', 'MONTHLY') {_s_month_where}
                GROUP BY s.account_id, a.account_name ORDER BY 총판매액 DESC
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
                    s.revenue_date_from as "매출시작",
                    s.revenue_date_to as "매출종료"
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
