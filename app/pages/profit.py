"""
순이익 분석 페이지
==================
일별 매출/원가/광고비/순이익 분석.
dashboard.py에서 분리한 순이익 탭.

순이익 = 정산금액 - 원가(COGS) - 택배비(2300원×건수) - 광고비
"""

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from sqlalchemy import text

from app.dashboard_utils import (
    query_df,
    fmt_krw,
    engine,
)

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent.parent

# 택배비 단가 (원)
COURIER_COST = 2300
# product 없는 listings의 추정 공급률 (평균)
DEFAULT_SUPPLY_RATE = 0.6


# ─── 헬퍼 ───


def _delta(cur, prev):
    """전기대비 변화율 표시"""
    if prev == 0:
        return None
    pct = round((cur - prev) / abs(prev) * 100)
    return f"{'+' if pct > 0 else ''}{pct}%"


def _fmt_profit_df(df):
    """순이익 테이블 금액 포맷 (모든 숫자 컬럼에 천단위 쉼표)"""
    d = df.copy()
    pct_cols = {"이익률(%)", "원가커버리지(%)", "광고비비중(%)"}
    skip_cols = {"#", "날짜", "계정"}
    for col in d.columns:
        if col in skip_cols:
            continue
        if col in pct_cols:
            d[col] = d[col].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "-")
        elif pd.api.types.is_numeric_dtype(d[col]):
            d[col] = d[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")
    return d


def _query_daily_revenue(d_from, d_to, acct_where):
    """일별 매출+원가 집계"""
    return query_df(f"""
        SELECT
            r.recognition_date as 날짜,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as 매출,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END) as 정산,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.service_fee + r.service_fee_vat ELSE 0 END) as 수수료,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as 판매수량,
            SUM(CASE WHEN r.sale_type='REFUND' THEN r.quantity ELSE 0 END) as 환불수량,
            SUM(CASE WHEN r.sale_type='SALE' THEN
                COALESCE(
                    NULLIF(l.supply_price, 0),
                    CAST(p.list_price * p.supply_rate AS INTEGER),
                    CAST(NULLIF(l.original_price, 0) * {DEFAULT_SUPPLY_RATE} AS INTEGER),
                    0
                ) * r.quantity
            WHEN r.sale_type='REFUND' THEN
                -COALESCE(
                    NULLIF(l.supply_price, 0),
                    CAST(p.list_price * p.supply_rate AS INTEGER),
                    CAST(NULLIF(l.original_price, 0) * {DEFAULT_SUPPLY_RATE} AS INTEGER),
                    0
                ) * r.quantity
            ELSE 0 END) as 원가,
            SUM(CASE
                WHEN r.sale_type IN ('SALE', 'REFUND')
                AND (NULLIF(l.supply_price, 0) IS NOT NULL OR p.supply_rate IS NOT NULL OR NULLIF(l.original_price, 0) IS NOT NULL)
                THEN CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE -r.quantity END
            ELSE 0 END) as 원가매칭수량
        FROM revenue_history r
        LEFT JOIN listings l ON r.listing_id = l.id
        LEFT JOIN products p ON l.product_id = p.id
        WHERE r.recognition_date BETWEEN '{d_from}' AND '{d_to}' {acct_where}
        GROUP BY r.recognition_date
        ORDER BY r.recognition_date
    """)


def _query_daily_ad(d_from, d_to, acct_where_ad):
    """일별 광고비 집계"""
    return query_df(f"""
        SELECT
            ad.ad_date as 날짜,
            SUM(ad.total_charge) as 광고비
        FROM ad_spends ad
        WHERE ad.ad_date BETWEEN '{d_from}' AND '{d_to}' {acct_where_ad}
        GROUP BY ad.ad_date
    """)


def _merge_profit(daily_rev, daily_ad):
    """매출+광고비 병합 → 순이익 계산"""
    daily_rev["날짜"] = daily_rev["날짜"].astype(str)

    if not daily_ad.empty:
        daily_ad["날짜"] = daily_ad["날짜"].astype(str)
        daily = daily_rev.merge(daily_ad, on="날짜", how="left").fillna({"광고비": 0})
    else:
        daily = daily_rev.copy()
        daily["광고비"] = 0

    daily["택배비"] = daily["판매수량"] * COURIER_COST
    daily["순이익"] = daily["정산"] - daily["원가"] - daily["택배비"] - daily["광고비"]
    daily["이익률"] = (daily["순이익"] / daily["매출"].replace(0, pd.NA) * 100).round(1)
    return daily


def _calc_totals(daily):
    """DataFrame에서 기간 합계 추출"""
    return {
        "매출": int(daily["매출"].sum()),
        "정산": int(daily["정산"].sum()),
        "원가": int(daily["원가"].sum()),
        "광고비": int(daily["광고비"].sum()),
        "택배비": int(daily["택배비"].sum()),
        "판매수량": int(daily["판매수량"].sum()),
        "원가매칭수량": int(daily["원가매칭수량"].sum()),
    }


# ─── 메인 렌더 ───

def render(selected_account, accounts_df, account_names):
    """순이익 분석 페이지 렌더링"""

    st.title("순이익 분석")

    # ── 상단 컨트롤 ──
    ctrl1, ctrl2, ctrl3 = st.columns([3, 3, 2])
    with ctrl1:
        period_opt = st.selectbox("기간", ["1주", "1개월", "3개월"], index=1, key="profit_period")
    with ctrl2:
        account_filter = st.selectbox("계정", ["전체"] + account_names, key="profit_acct")
    with ctrl3:
        st.markdown("<br>", unsafe_allow_html=True)
        btn_sync = st.button("매출 동기화", type="primary", key="btn_profit_sync", width="stretch")

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

    # ── 동기화 ──
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

    # ── 계정 필터 ──
    acct_where = ""       # revenue_history 용 (alias r)
    acct_where_ad = ""    # ad_spends 용 (alias ad)
    _acct_id = None
    if account_filter != "전체":
        _aid_row = query_df(
            "SELECT id FROM accounts WHERE account_name = :name LIMIT 1",
            {"name": account_filter},
        )
        if _aid_row.empty:
            st.error(f"계정 '{account_filter}'을 찾을 수 없습니다.")
            st.stop()
        _acct_id = int(_aid_row.iloc[0]["id"])
        acct_where = f"AND r.account_id = {_acct_id}"
        acct_where_ad = f"AND ad.account_id = {_acct_id}"

    # ── 현재 기간 데이터 ──
    daily_rev = _query_daily_revenue(date_from_str, date_to_str, acct_where)
    daily_ad = _query_daily_ad(date_from_str, date_to_str, acct_where_ad)

    if daily_rev.empty or daily_rev["매출"].sum() == 0:
        st.info("해당 기간 매출 데이터가 없습니다. '매출 동기화' 버튼을 눌러주세요.")
        st.stop()

    daily = _merge_profit(daily_rev, daily_ad)
    cur = _calc_totals(daily)
    cur_profit = cur["정산"] - cur["원가"] - cur["택배비"] - cur["광고비"]
    cur_margin = round(cur_profit / cur["매출"] * 100, 1) if cur["매출"] else 0.0
    has_ad_data = not daily_ad.empty and daily_ad["광고비"].sum() > 0

    # ── 전기 데이터 (delta 계산용) ──
    prev_rev = _query_daily_revenue(prev_from_str, prev_to_str, acct_where)
    prev_ad = _query_daily_ad(prev_from_str, prev_to_str, acct_where_ad)

    if not prev_rev.empty and prev_rev["매출"].sum() > 0:
        prev_daily = _merge_profit(prev_rev, prev_ad)
        prv = _calc_totals(prev_daily)
        prv_profit = prv["정산"] - prv["원가"] - prv["택배비"] - prv["광고비"]
        prv_margin = round(prv_profit / prv["매출"] * 100, 1) if prv["매출"] else 0.0
    else:
        prv = {"매출": 0, "정산": 0, "원가": 0, "광고비": 0, "택배비": 0}
        prv_profit = 0
        prv_margin = 0.0

    # ── KPI 카드 (6개) ──
    kc1, kc2, kc3, kc4, kc5, kc6 = st.columns(6)
    kc1.metric("총매출", fmt_krw(cur["매출"]), delta=_delta(cur["매출"], prv["매출"]))
    kc2.metric("정산금액", fmt_krw(cur["정산"]), delta=_delta(cur["정산"], prv["정산"]))
    kc3.metric("추정원가", fmt_krw(cur["원가"]), delta=_delta(cur["원가"], prv["원가"]), delta_color="inverse")
    kc4.metric("광고비", fmt_krw(cur["광고비"]), delta=_delta(cur["광고비"], prv["광고비"]), delta_color="inverse")
    kc5.metric("순이익", fmt_krw(cur_profit), delta=_delta(cur_profit, prv_profit))
    kc6.metric("이익률", f"{cur_margin}%", delta=_delta(cur_margin, prv_margin))

    st.caption(f"{date_from_str} ~ {date_to_str}  |  비교: {prev_from_str} ~ {prev_to_str}")

    # ── 데이터 커버리지 안내 ──
    _notices = []
    if not has_ad_data:
        _notices.append("광고비 데이터 없음 — 광고비 0원으로 계산됩니다")
    cogs_coverage = round(cur["원가매칭수량"] / cur["판매수량"] * 100, 1) if cur["판매수량"] > 0 else 0
    if cogs_coverage < 100:
        _notices.append(f"원가 추정 커버리지: {cogs_coverage}% ({cur['원가매칭수량']}/{cur['판매수량']}건)")
    if _notices:
        st.caption("  |  ".join(f"⚠️ {n}" for n in _notices))

    # ── 인사이트 ──
    _insights = []

    # 순이익 전기대비
    if prv_profit != 0:
        _pf_pct = round((cur_profit - prv_profit) / abs(prv_profit) * 100)
        _pf_diff = fmt_krw(abs(cur_profit - prv_profit))
        if _pf_pct > 5:
            _insights.append(f"순이익 전기 대비 **{_pf_pct}% 상승** ({_pf_diff} 증가)")
        elif _pf_pct < -5:
            _insights.append(f"순이익 전기 대비 **{abs(_pf_pct)}% 하락** ({_pf_diff} 감소)")
        else:
            _insights.append("전기 대비 순이익 **비슷한 수준** 유지")

    # 광고비 비중
    if cur["광고비"] > 0 and cur["매출"] > 0:
        ad_ratio = round(cur["광고비"] / cur["매출"] * 100, 1)
        _insights.append(f"광고비 비중: 매출 대비 **{ad_ratio}%** ({fmt_krw(cur['광고비'])})")

    # 최고/최저 수익일
    if len(daily) > 1:
        best_idx = daily["순이익"].idxmax()
        worst_idx = daily["순이익"].idxmin()
        best_day = daily.loc[best_idx]
        worst_day = daily.loc[worst_idx]
        _insights.append(f"최고 수익일: **{best_day['날짜']}** ({fmt_krw(int(best_day['순이익']))})")
        if int(worst_day["순이익"]) < 0:
            _insights.append(f"최저 수익일: **{worst_day['날짜']}** ({fmt_krw(int(worst_day['순이익']))})")

    # COGS 커버리지
    if 0 < cogs_coverage < 80:
        _insights.append(f"원가 데이터 커버리지 **{cogs_coverage}%** — listing 상세 동기화로 개선 가능")

    if _insights:
        st.markdown("**💡 주요 인사이트**")
        for ins in _insights:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;• {ins}")

    st.divider()

    # ── 일별 추이 차트 (Plotly dual axis) ──
    daily_chart = daily.copy()
    daily_chart["날짜_dt"] = pd.to_datetime(daily_chart["날짜"])

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 매출 bar
    fig.add_trace(
        go.Bar(
            x=daily_chart["날짜_dt"], y=daily_chart["매출"],
            name="매출", marker_color="rgba(99, 110, 250, 0.5)",
        ),
        secondary_y=False,
    )

    # 순이익 bar (양수=녹색, 음수=빨강)
    profit_colors = [
        "rgba(0, 204, 150, 0.8)" if v >= 0 else "rgba(239, 85, 59, 0.8)"
        for v in daily_chart["순이익"]
    ]
    fig.add_trace(
        go.Bar(
            x=daily_chart["날짜_dt"], y=daily_chart["순이익"],
            name="순이익", marker_color=profit_colors,
        ),
        secondary_y=False,
    )

    # 이익률 line
    fig.add_trace(
        go.Scatter(
            x=daily_chart["날짜_dt"], y=daily_chart["이익률"],
            name="이익률(%)", line=dict(color="#FFA15A", width=2),
            mode="lines+markers",
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title="일별 매출 & 순이익 추이",
        barmode="group",
        hovermode="x unified",
        margin=dict(t=40, b=10, l=10, r=10),
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="금액 (원)", secondary_y=False)
    fig.update_yaxes(title_text="이익률 (%)", secondary_y=True)

    st.plotly_chart(fig, width="stretch")

    # ── 하단 탭 ──
    if account_filter == "전체":
        tab_detail, tab_compare = st.tabs(["📊 일별 상세", "🏢 계정별 비교"])
    else:
        tab_detail, tab_products = st.tabs(["📊 일별 상세", "📦 상품별 수익"])

    # ── 탭 1: 일별 상세 ──
    with tab_detail:
        detail_cols = ["날짜", "매출", "수수료", "원가", "택배비", "광고비", "정산", "순이익"]
        detail_df = daily[detail_cols].copy()
        detail_df["이익률(%)"] = daily["이익률"]
        st.dataframe(_fmt_profit_df(detail_df), width="stretch", hide_index=True)
        _csv = detail_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 일별 상세 CSV", _csv,
            f"daily_profit_{date_from_str}.csv", "text/csv",
            key="dl_profit_daily",
        )

    # ── 탭 2: 계정별 비교 (전체) / 상품별 수익 (개별) ──
    if account_filter == "전체":
        with tab_compare:
            _render_account_compare(date_from_str, date_to_str)
    else:
        with tab_products:
            _render_product_profit(
                _acct_id, account_filter,
                date_from_str, date_to_str,
                int(daily["광고비"].sum()),
            )


# ─── 계정별 비교 서브렌더 ───

def _render_account_compare(date_from_str, date_to_str):
    """계정별 순이익 비교 (전체 선택 시)"""
    acct_profit = query_df(f"""
        SELECT
            a.account_name as 계정,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as 매출,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END) as 정산,
            SUM(CASE WHEN r.sale_type='SALE' THEN
                COALESCE(
                    NULLIF(l.supply_price, 0),
                    CAST(p.list_price * p.supply_rate AS INTEGER),
                    CAST(NULLIF(l.original_price, 0) * {DEFAULT_SUPPLY_RATE} AS INTEGER),
                    0
                ) * r.quantity
            WHEN r.sale_type='REFUND' THEN
                -COALESCE(
                    NULLIF(l.supply_price, 0),
                    CAST(p.list_price * p.supply_rate AS INTEGER),
                    CAST(NULLIF(l.original_price, 0) * {DEFAULT_SUPPLY_RATE} AS INTEGER),
                    0
                ) * r.quantity
            ELSE 0 END) as 원가,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as 판매수량
        FROM revenue_history r
        JOIN accounts a ON r.account_id = a.id
        LEFT JOIN listings l ON r.listing_id = l.id
        LEFT JOIN products p ON l.product_id = p.id
        WHERE r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
        GROUP BY r.account_id, a.account_name
        ORDER BY 매출 DESC
    """)
    if acct_profit.empty:
        st.info("계정별 데이터가 없습니다.")
        return

    # 계정별 광고비 조인
    acct_ad = query_df(f"""
        SELECT
            ac.account_name as 계정,
            SUM(ad.total_charge) as 광고비
        FROM ad_spends ad
        JOIN accounts ac ON ad.account_id = ac.id
        WHERE ad.ad_date BETWEEN '{date_from_str}' AND '{date_to_str}'
        GROUP BY ad.account_id, ac.account_name
    """)
    if not acct_ad.empty:
        acct_profit = acct_profit.merge(acct_ad, on="계정", how="left").fillna({"광고비": 0})
    else:
        acct_profit["광고비"] = 0

    acct_profit["택배비"] = acct_profit["판매수량"] * COURIER_COST
    acct_profit["순이익"] = (
        acct_profit["정산"] - acct_profit["원가"]
        - acct_profit["택배비"] - acct_profit["광고비"]
    )
    acct_profit["이익률(%)"] = (
        acct_profit["순이익"] / acct_profit["매출"].replace(0, pd.NA) * 100
    ).round(1)

    display_cols = ["계정", "매출", "정산", "원가", "택배비", "광고비", "순이익", "이익률(%)"]
    acct_display = acct_profit[display_cols]

    # 차트
    import plotly.express as px

    _chart_col, _pie_col = st.columns([3, 2])
    with _chart_col:
        fig_acct = px.bar(
            acct_display, x="계정", y=["매출", "순이익"],
            barmode="group", title="계정별 매출 vs 순이익",
            color_discrete_sequence=["#636EFA", "#00CC96"],
        )
        fig_acct.update_layout(
            margin=dict(t=40, b=10, l=10, r=10), height=350,
            yaxis_title="금액 (원)",
        )
        st.plotly_chart(fig_acct, width="stretch")
    with _pie_col:
        _pie_data = acct_display[acct_display["순이익"] > 0]
        if not _pie_data.empty:
            fig_pie = px.pie(
                _pie_data, values="순이익", names="계정",
                title="순이익 비중", hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_pie.update_layout(
                margin=dict(t=40, b=10, l=10, r=10), height=350, showlegend=True,
            )
            st.plotly_chart(fig_pie, width="stretch")

    st.dataframe(_fmt_profit_df(acct_display), width="stretch", hide_index=True)
    _csv = acct_display.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 계정별 비교 CSV", _csv,
        f"account_profit_{date_from_str}.csv", "text/csv",
        key="dl_profit_acct",
    )


# ─── 상품별 수익 서브렌더 ───

def _render_product_profit(acct_id, account_name, date_from_str, date_to_str, total_ad_cost):
    """상품별 수익 Top 20 (개별 계정 선택 시)"""
    prod_profit = query_df(f"""
        SELECT
            r.product_name as 상품명,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.quantity ELSE 0 END) as 판매수량,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.sale_amount ELSE -r.sale_amount END) as 매출,
            SUM(CASE WHEN r.sale_type='SALE' THEN r.settlement_amount ELSE -r.settlement_amount END) as 정산,
            SUM(CASE WHEN r.sale_type='SALE' THEN
                COALESCE(
                    NULLIF(l.supply_price, 0),
                    CAST(p.list_price * p.supply_rate AS INTEGER),
                    CAST(NULLIF(l.original_price, 0) * {DEFAULT_SUPPLY_RATE} AS INTEGER),
                    0
                ) * r.quantity
            WHEN r.sale_type='REFUND' THEN
                -COALESCE(
                    NULLIF(l.supply_price, 0),
                    CAST(p.list_price * p.supply_rate AS INTEGER),
                    CAST(NULLIF(l.original_price, 0) * {DEFAULT_SUPPLY_RATE} AS INTEGER),
                    0
                ) * r.quantity
            ELSE 0 END) as 원가
        FROM revenue_history r
        LEFT JOIN listings l ON r.listing_id = l.id
        LEFT JOIN products p ON l.product_id = p.id
        WHERE r.account_id = {acct_id}
          AND r.recognition_date BETWEEN '{date_from_str}' AND '{date_to_str}'
        GROUP BY r.vendor_item_id, r.product_name
        ORDER BY 매출 DESC
        LIMIT 20
    """)
    if prod_profit.empty:
        st.info("상품별 수익 데이터가 없습니다.")
        return

    prod_profit["택배비"] = prod_profit["판매수량"] * COURIER_COST

    # 광고비를 매출 비중으로 안분
    total_rev = int(prod_profit["매출"].sum())
    if total_ad_cost > 0 and total_rev > 0:
        prod_profit["광고비(안분)"] = (
            prod_profit["매출"] / total_rev * total_ad_cost
        ).round(0).astype(int)
    else:
        prod_profit["광고비(안분)"] = 0

    prod_profit["추정순이익"] = (
        prod_profit["정산"] - prod_profit["원가"]
        - prod_profit["택배비"] - prod_profit["광고비(안분)"]
    )
    prod_profit.insert(0, "#", range(1, len(prod_profit) + 1))

    display_cols = [
        "#", "상품명", "판매수량", "매출", "정산",
        "원가", "택배비", "광고비(안분)", "추정순이익",
    ]
    st.dataframe(
        _fmt_profit_df(prod_profit[display_cols]),
        width="stretch", hide_index=True,
    )
    _csv = prod_profit[display_cols].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 상품별 수익 CSV", _csv,
        f"product_profit_{account_name}_{date_from_str}.csv", "text/csv",
        key="dl_profit_prod",
    )

    # Top 10 차트
    _top10 = prod_profit.head(10).copy()
    _top10["_label"] = _top10["상품명"].str[:20]

    import plotly.express as px
    fig_prod = px.bar(
        _top10, x="_label", y=["매출", "추정순이익"],
        barmode="group", title="상품별 매출 vs 추정순이익 (Top 10)",
        color_discrete_sequence=["#636EFA", "#00CC96"],
    )
    fig_prod.update_layout(
        margin=dict(t=40, b=10, l=10, r=10), height=350,
        xaxis_title="", yaxis_title="금액 (원)",
    )
    st.plotly_chart(fig_prod, width="stretch")
