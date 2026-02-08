"""
노출 전략 엔진
==============
상품별 종합 점수 산출 + 액션 아이템 생성 + 인사이트 분석

점수 가중치:
  판매 속도 35% | 광고 효율 25% | 재고 건강도 20% | 배송 경쟁력 20%
"""
import logging
from datetime import date, timedelta
from typing import List, Dict, Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class ExposureStrategyEngine:
    """노출 전략 분석 엔진"""

    # 점수 가중치
    WEIGHT_SALES = 0.35
    WEIGHT_AD = 0.25
    WEIGHT_STOCK = 0.20
    WEIGHT_SHIPPING = 0.20

    def __init__(self, engine: Engine):
        self.engine = engine

    # ══════════════════════════════════════
    # 상품 스코어링
    # ══════════════════════════════════════
    def get_product_scores(self, account_id: int, period_days: int = 14) -> pd.DataFrame:
        """
        상품별 종합 점수 계산

        Returns DataFrame:
          listing_id, product_name, isbn, sale_price,
          sales_velocity_score, ad_efficiency_score,
          stock_health_score, shipping_score,
          overall_score, grade, top_action
        """
        # 기본 리스팅 정보
        listings = self._get_active_listings(account_id)
        if listings.empty:
            return pd.DataFrame()

        # 각 점수 계산
        sales = self._calc_sales_velocity(account_id, period_days)
        ad_eff = self._calc_ad_efficiency(account_id, period_days)
        stock = self._calc_stock_health(account_id)
        shipping = self._calc_shipping_score(account_id)

        # 병합
        df = listings.copy()
        for sub_df, col in [(sales, "sales_velocity_score"), (ad_eff, "ad_efficiency_score"),
                            (stock, "stock_health_score"), (shipping, "shipping_score")]:
            if not sub_df.empty and "listing_id" in sub_df.columns:
                df = df.merge(sub_df[["listing_id", col]], on="listing_id", how="left")

        # 결측값 기본 점수
        df["sales_velocity_score"] = df.get("sales_velocity_score", pd.Series(50)).fillna(50)
        df["ad_efficiency_score"] = df.get("ad_efficiency_score", pd.Series(50)).fillna(50)
        df["stock_health_score"] = df.get("stock_health_score", pd.Series(50)).fillna(50)
        df["shipping_score"] = df.get("shipping_score", pd.Series(50)).fillna(50)

        # 종합 점수
        df["overall_score"] = (
            df["sales_velocity_score"] * self.WEIGHT_SALES
            + df["ad_efficiency_score"] * self.WEIGHT_AD
            + df["stock_health_score"] * self.WEIGHT_STOCK
            + df["shipping_score"] * self.WEIGHT_SHIPPING
        ).round(1)

        # 등급
        df["grade"] = df["overall_score"].apply(self._score_to_grade)

        # 최우선 액션
        df["top_action"] = df.apply(self._determine_top_action, axis=1)

        return df.sort_values("overall_score", ascending=False).reset_index(drop=True)

    def _get_active_listings(self, account_id: int) -> pd.DataFrame:
        """활성 리스팅 기본 정보"""
        sql = """
            SELECT l.id as listing_id,
                   l.product_name,
                   l.isbn,
                   l.sale_price,
                   l.stock_quantity,
                   l.delivery_charge_type,
                   l.coupang_product_id,
                   l.vendor_item_id
            FROM listings l
            WHERE l.account_id = :aid AND l.coupang_status = 'active'
        """
        with self.engine.connect() as conn:
            result = pd.read_sql(text(sql), conn, params={"aid": account_id})
        return result

    def _calc_sales_velocity(self, account_id: int, period_days: int) -> pd.DataFrame:
        """매출 속도 점수 (0-100)"""
        today = date.today()
        period_start = today - timedelta(days=period_days)
        prev_start = period_start - timedelta(days=period_days)

        sql = """
            SELECT
                r.listing_id,
                SUM(CASE WHEN r.recognition_date >= :period_start AND r.sale_type = 'SALE'
                         THEN r.quantity ELSE 0 END) as current_qty,
                SUM(CASE WHEN r.recognition_date >= :period_start AND r.sale_type = 'SALE'
                         THEN r.sale_amount ELSE 0 END) as current_revenue,
                SUM(CASE WHEN r.recognition_date < :period_start
                              AND r.recognition_date >= :prev_start
                              AND r.sale_type = 'SALE'
                         THEN r.quantity ELSE 0 END) as prev_qty,
                SUM(CASE WHEN r.recognition_date < :period_start
                              AND r.recognition_date >= :prev_start
                              AND r.sale_type = 'SALE'
                         THEN r.sale_amount ELSE 0 END) as prev_revenue
            FROM revenue_history r
            WHERE r.account_id = :aid
                AND r.recognition_date >= :prev_start
                AND r.listing_id IS NOT NULL
            GROUP BY r.listing_id
        """
        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params={
                "aid": account_id,
                "period_start": period_start.isoformat(),
                "prev_start": prev_start.isoformat(),
            })

        if df.empty:
            return pd.DataFrame(columns=["listing_id", "sales_velocity_score"])

        # 성장률 계산
        df["growth_rate"] = df.apply(
            lambda r: ((r["current_qty"] - r["prev_qty"]) / r["prev_qty"] * 100)
            if r["prev_qty"] > 0 else (100 if r["current_qty"] > 0 else 0),
            axis=1,
        )

        # 판매량 기준 백분위 (상대 평가)
        max_qty = df["current_qty"].max()
        if max_qty > 0:
            df["qty_percentile"] = (df["current_qty"] / max_qty * 60).clip(0, 60)
        else:
            df["qty_percentile"] = 0

        # 성장률 기준 점수 (최대 40점)
        df["growth_score"] = df["growth_rate"].apply(
            lambda g: min(40, max(0, 20 + g * 0.2))
        )

        df["sales_velocity_score"] = (df["qty_percentile"] + df["growth_score"]).clip(0, 100).round(1)

        return df[["listing_id", "sales_velocity_score", "current_qty", "current_revenue",
                    "prev_qty", "prev_revenue", "growth_rate"]]

    def _calc_ad_efficiency(self, account_id: int, period_days: int) -> pd.DataFrame:
        """광고 효율 점수 (0-100)"""
        today = date.today()
        period_start = today - timedelta(days=period_days)

        sql = """
            SELECT
                ap.listing_id,
                SUM(ap.impressions) as total_impressions,
                SUM(ap.clicks) as total_clicks,
                SUM(ap.ad_spend) as total_spend,
                SUM(ap.total_revenue) as total_revenue,
                SUM(ap.total_orders) as total_orders
            FROM ad_performances ap
            WHERE ap.account_id = :aid
                AND ap.ad_date >= :period_start
                AND ap.listing_id IS NOT NULL
            GROUP BY ap.listing_id
        """
        try:
            with self.engine.connect() as conn:
                df = pd.read_sql(text(sql), conn, params={
                    "aid": account_id,
                    "period_start": period_start.isoformat(),
                })
        except Exception:
            # 테이블이 아직 없을 수 있음
            return pd.DataFrame(columns=["listing_id", "ad_efficiency_score"])

        if df.empty:
            return pd.DataFrame(columns=["listing_id", "ad_efficiency_score"])

        # ROAS 기반 점수
        df["roas_pct"] = df.apply(
            lambda r: (r["total_revenue"] / r["total_spend"] * 100) if r["total_spend"] > 0 else 0,
            axis=1,
        )

        # ROAS → 점수 변환
        # 300%+ = 90~100, 200-300% = 70~90, 100-200% = 40~70, <100% = 0~40
        def roas_to_score(roas):
            if roas >= 300:
                return min(100, 90 + (roas - 300) / 100 * 10)
            elif roas >= 200:
                return 70 + (roas - 200) / 100 * 20
            elif roas >= 100:
                return 40 + (roas - 100) / 100 * 30
            else:
                return max(0, roas / 100 * 40)

        df["ad_efficiency_score"] = df["roas_pct"].apply(roas_to_score).round(1)

        return df[["listing_id", "ad_efficiency_score"]]

    def _calc_stock_health(self, account_id: int) -> pd.DataFrame:
        """재고 건강도 점수 (0-100)"""
        sql = """
            SELECT id as listing_id, stock_quantity
            FROM listings
            WHERE account_id = :aid AND coupang_status = 'active'
        """
        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params={"aid": account_id})

        if df.empty:
            return pd.DataFrame(columns=["listing_id", "stock_health_score"])

        def stock_to_score(qty):
            if qty is None:
                qty = 0
            if qty >= 10:
                return 100
            elif qty >= 5:
                return 70
            elif qty >= 1:
                return 30
            else:
                return 0

        df["stock_health_score"] = df["stock_quantity"].apply(stock_to_score)
        return df[["listing_id", "stock_health_score"]]

    def _calc_shipping_score(self, account_id: int) -> pd.DataFrame:
        """배송 경쟁력 점수 (0-100)"""
        sql = """
            SELECT id as listing_id, delivery_charge_type
            FROM listings
            WHERE account_id = :aid AND coupang_status = 'active'
        """
        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params={"aid": account_id})

        if df.empty:
            return pd.DataFrame(columns=["listing_id", "shipping_score"])

        def shipping_to_score(charge_type):
            if not charge_type:
                return 50  # 정보 없음 → 중립
            ct = str(charge_type).upper()
            if ct == "FREE":
                return 100
            elif ct == "CONDITIONAL_FREE":
                return 70
            else:  # NOT_FREE 등
                return 30

        df["shipping_score"] = df["delivery_charge_type"].apply(shipping_to_score)
        return df[["listing_id", "shipping_score"]]

    @staticmethod
    def _score_to_grade(score: float) -> str:
        if score >= 80:
            return "A"
        elif score >= 60:
            return "B"
        elif score >= 40:
            return "C"
        elif score >= 20:
            return "D"
        return "F"

    @staticmethod
    def _determine_top_action(row) -> str:
        """점수가 가장 낮은 영역의 액션 추천"""
        scores = {
            "재고 보충": row.get("stock_health_score", 50),
            "배송 정책 개선": row.get("shipping_score", 50),
            "광고 최적화": row.get("ad_efficiency_score", 50),
            "판매 촉진": row.get("sales_velocity_score", 50),
        }
        weakest = min(scores, key=scores.get)
        weakest_score = scores[weakest]

        if weakest_score >= 70:
            return "현상 유지"
        return weakest

    # ══════════════════════════════════════
    # 액션 아이템
    # ══════════════════════════════════════
    def get_action_items(self, account_id: int, period_days: int = 14) -> List[dict]:
        """우선순위 정렬된 액션 아이템"""
        items = []
        today = date.today()
        period_start = today - timedelta(days=period_days)
        prev_start = period_start - timedelta(days=period_days)

        # ── 재고 기반 액션 ──
        with self.engine.connect() as conn:
            stock_df = pd.read_sql(text("""
                SELECT l.id as listing_id, l.product_name, l.stock_quantity, l.isbn
                FROM listings l
                WHERE l.account_id = :aid AND l.coupang_status = 'active'
            """), conn, params={"aid": account_id})

        # 최근 판매 있는 상품 확인
        with self.engine.connect() as conn:
            recent_sales = pd.read_sql(text("""
                SELECT listing_id, SUM(quantity) as qty
                FROM revenue_history
                WHERE account_id = :aid AND sale_type = 'SALE'
                    AND recognition_date >= :start
                GROUP BY listing_id
            """), conn, params={"aid": account_id, "start": period_start.isoformat()})

        recent_selling = set(recent_sales["listing_id"].tolist()) if not recent_sales.empty else set()

        for _, row in stock_df.iterrows():
            stock = row["stock_quantity"] or 0
            lid = row["listing_id"]
            name = row["product_name"] or row.get("isbn", "")

            if stock == 0:
                items.append({
                    "priority": "critical",
                    "icon": "🔴",
                    "listing_id": lid,
                    "product_name": name,
                    "action": "즉시 재고 보충",
                    "reason": "품절 상태 → 알고리즘 노출 중단",
                    "metric": f"재고: {stock}개",
                })
            elif stock <= 3 and lid in recent_selling:
                items.append({
                    "priority": "critical",
                    "icon": "🔴",
                    "listing_id": lid,
                    "product_name": name,
                    "action": "재고 보충 긴급",
                    "reason": "최근 판매 발생 + 재고 부족",
                    "metric": f"재고: {stock}개",
                })
            elif 4 <= stock <= 5:
                items.append({
                    "priority": "warning",
                    "icon": "🟡",
                    "listing_id": lid,
                    "product_name": name,
                    "action": "재고 부족 주의",
                    "reason": "재고가 소진될 수 있음",
                    "metric": f"재고: {stock}개",
                })

        # ── 매출 변동 액션 ──
        with self.engine.connect() as conn:
            sales_comp = pd.read_sql(text("""
                SELECT
                    r.listing_id,
                    l.product_name,
                    SUM(CASE WHEN r.recognition_date >= :period_start AND r.sale_type = 'SALE'
                             THEN r.sale_amount ELSE 0 END) as current_rev,
                    SUM(CASE WHEN r.recognition_date < :period_start
                                  AND r.recognition_date >= :prev_start
                                  AND r.sale_type = 'SALE'
                             THEN r.sale_amount ELSE 0 END) as prev_rev
                FROM revenue_history r
                JOIN listings l ON r.listing_id = l.id
                WHERE r.account_id = :aid
                    AND r.recognition_date >= :prev_start
                    AND r.listing_id IS NOT NULL
                GROUP BY r.listing_id
            """), conn, params={
                "aid": account_id,
                "period_start": period_start.isoformat(),
                "prev_start": prev_start.isoformat(),
            })

        if not sales_comp.empty:
            for _, row in sales_comp.iterrows():
                prev = row["prev_rev"] or 0
                curr = row["current_rev"] or 0
                name = row["product_name"] or ""

                if prev > 0:
                    change_pct = (curr - prev) / prev * 100

                    if change_pct <= -50:
                        items.append({
                            "priority": "critical",
                            "icon": "🔴",
                            "listing_id": row["listing_id"],
                            "product_name": name,
                            "action": "매출 급감 원인 파악",
                            "reason": f"전기간 대비 매출 {change_pct:.0f}% 감소",
                            "metric": f"₩{int(prev):,} → ₩{int(curr):,}",
                        })
                    elif change_pct >= 30:
                        items.append({
                            "priority": "opportunity",
                            "icon": "🟢",
                            "listing_id": row["listing_id"],
                            "product_name": name,
                            "action": "광고 투자 확대 추천",
                            "reason": f"매출 성장 추세 ({change_pct:.0f}%↑)",
                            "metric": f"₩{int(prev):,} → ₩{int(curr):,}",
                        })

        # ── 광고 효율 액션 ──
        try:
            with self.engine.connect() as conn:
                ad_eff = pd.read_sql(text("""
                    SELECT
                        ap.listing_id,
                        l.product_name,
                        SUM(ap.ad_spend) as spend,
                        SUM(ap.total_revenue) as revenue,
                        SUM(ap.total_orders) as orders
                    FROM ad_performances ap
                    JOIN listings l ON ap.listing_id = l.id
                    WHERE ap.account_id = :aid
                        AND ap.ad_date >= :start
                        AND ap.listing_id IS NOT NULL
                    GROUP BY ap.listing_id
                """), conn, params={"aid": account_id, "start": period_start.isoformat()})

            for _, row in ad_eff.iterrows():
                spend = row["spend"] or 0
                revenue = row["revenue"] or 0
                name = row["product_name"] or ""
                roas = (revenue / spend * 100) if spend > 0 else 0

                if spend > 0 and roas < 100:
                    items.append({
                        "priority": "warning",
                        "icon": "🟡",
                        "listing_id": row["listing_id"],
                        "product_name": name,
                        "action": "광고 효율 낮음, 키워드/예산 조정",
                        "reason": f"ROAS {roas:.0f}% (손익분기 미달)",
                        "metric": f"광고비 ₩{int(spend):,} → 매출 ₩{int(revenue):,}",
                    })
                elif spend > 0 and roas >= 300:
                    items.append({
                        "priority": "opportunity",
                        "icon": "🟢",
                        "listing_id": row["listing_id"],
                        "product_name": name,
                        "action": "광고 예산 증액 추천",
                        "reason": f"ROAS {roas:.0f}%로 높은 효율",
                        "metric": f"광고비 ₩{int(spend):,} → 매출 ₩{int(revenue):,}",
                    })
        except Exception:
            pass  # ad_performances 테이블 없으면 스킵

        # ── 배송 정책 액션 ──
        for _, row in stock_df.iterrows():
            # delivery_charge_type 정보는 stock_df에 없으므로 별도 조회
            pass

        with self.engine.connect() as conn:
            ship_df = pd.read_sql(text("""
                SELECT id as listing_id, product_name, delivery_charge_type
                FROM listings
                WHERE account_id = :aid AND coupang_status = 'active'
                    AND delivery_charge_type = 'NOT_FREE'
            """), conn, params={"aid": account_id})

        for _, row in ship_df.iterrows():
            items.append({
                "priority": "warning",
                "icon": "🟡",
                "listing_id": row["listing_id"],
                "product_name": row["product_name"] or "",
                "action": "무료배송 전환 검토",
                "reason": "유료배송 → 노출 순위 불이익",
                "metric": f"배송: {row['delivery_charge_type']}",
            })

        # ── 광고 없이 매출 발생 (기회) ──
        try:
            with self.engine.connect() as conn:
                no_ad_sales = pd.read_sql(text("""
                    SELECT r.listing_id, l.product_name,
                           SUM(r.sale_amount) as revenue
                    FROM revenue_history r
                    JOIN listings l ON r.listing_id = l.id
                    WHERE r.account_id = :aid
                        AND r.sale_type = 'SALE'
                        AND r.recognition_date >= :start
                        AND r.listing_id IS NOT NULL
                        AND r.listing_id NOT IN (
                            SELECT DISTINCT listing_id FROM ad_performances
                            WHERE account_id = :aid AND ad_date >= :start AND listing_id IS NOT NULL
                        )
                    GROUP BY r.listing_id
                    HAVING SUM(r.sale_amount) > 0
                    ORDER BY revenue DESC
                    LIMIT 10
                """), conn, params={"aid": account_id, "start": period_start.isoformat()})

            for _, row in no_ad_sales.iterrows():
                items.append({
                    "priority": "opportunity",
                    "icon": "🟢",
                    "listing_id": row["listing_id"],
                    "product_name": row["product_name"] or "",
                    "action": "광고 시작 추천",
                    "reason": "광고 없이 자연 매출 발생 중",
                    "metric": f"매출 ₩{int(row['revenue']):,}",
                })
        except Exception:
            pass

        # 우선순위 정렬: critical → warning → opportunity
        priority_order = {"critical": 0, "warning": 1, "opportunity": 2}
        items.sort(key=lambda x: priority_order.get(x["priority"], 3))

        return items

    # ══════════════════════════════════════
    # 광고 분석
    # ══════════════════════════════════════
    def get_ad_summary(self, account_id: int, period_days: int = 30) -> dict:
        """광고 성과 요약"""
        today = date.today()
        start = today - timedelta(days=period_days)

        try:
            with self.engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT
                        COALESCE(SUM(impressions), 0) as total_impressions,
                        COALESCE(SUM(clicks), 0) as total_clicks,
                        COALESCE(SUM(ad_spend), 0) as total_spend,
                        COALESCE(SUM(total_revenue), 0) as total_revenue,
                        COALESCE(SUM(total_orders), 0) as total_orders
                    FROM ad_performances
                    WHERE account_id = :aid AND ad_date >= :start
                """), {"aid": account_id, "start": start.isoformat()}).mappings().first()

            if not row:
                return self._empty_ad_summary()

            total_spend = row["total_spend"]
            total_rev = row["total_revenue"]
            total_clicks = row["total_clicks"]
            total_impressions = row["total_impressions"]

            return {
                "total_impressions": total_impressions,
                "total_clicks": total_clicks,
                "avg_ctr": round(total_clicks / total_impressions * 100, 2) if total_impressions > 0 else 0,
                "total_spend": total_spend,
                "total_revenue": total_rev,
                "roas": round(total_rev / total_spend * 100, 1) if total_spend > 0 else 0,
                "total_orders": row["total_orders"],
                "has_data": True,
            }
        except Exception:
            return self._empty_ad_summary()

    @staticmethod
    def _empty_ad_summary() -> dict:
        return {
            "total_impressions": 0, "total_clicks": 0, "avg_ctr": 0,
            "total_spend": 0, "total_revenue": 0, "roas": 0,
            "total_orders": 0, "has_data": False,
        }

    def get_ad_product_ranking(self, account_id: int, period_days: int = 30) -> pd.DataFrame:
        """상품별 광고 성과 랭킹"""
        today = date.today()
        start = today - timedelta(days=period_days)

        try:
            with self.engine.connect() as conn:
                df = pd.read_sql(text("""
                    SELECT
                        ap.coupang_product_id as 상품ID,
                        COALESCE(ap.product_name, l.product_name, '') as 상품명,
                        SUM(ap.impressions) as 노출수,
                        SUM(ap.clicks) as 클릭수,
                        CASE WHEN SUM(ap.impressions) > 0
                             THEN ROUND(SUM(ap.clicks) * 100.0 / SUM(ap.impressions), 2)
                             ELSE 0 END as "CTR(%)",
                        SUM(ap.ad_spend) as 광고비,
                        SUM(ap.total_orders) as 주문수,
                        SUM(ap.total_revenue) as 매출,
                        CASE WHEN SUM(ap.ad_spend) > 0
                             THEN ROUND(SUM(ap.total_revenue) * 100.0 / SUM(ap.ad_spend), 1)
                             ELSE 0 END as "ROAS(%)"
                    FROM ad_performances ap
                    LEFT JOIN listings l ON ap.listing_id = l.id
                    WHERE ap.account_id = :aid AND ap.ad_date >= :start
                        AND ap.report_type = 'product'
                    GROUP BY ap.coupang_product_id
                    ORDER BY 매출 DESC
                """), conn, params={"aid": account_id, "start": start.isoformat()})
            return df
        except Exception:
            return pd.DataFrame()

    def get_ad_keyword_ranking(self, account_id: int, period_days: int = 30) -> pd.DataFrame:
        """키워드별 광고 성과 랭킹"""
        today = date.today()
        start = today - timedelta(days=period_days)

        try:
            with self.engine.connect() as conn:
                df = pd.read_sql(text("""
                    SELECT
                        ap.keyword as 키워드,
                        ap.match_type as 매치유형,
                        SUM(ap.impressions) as 노출수,
                        SUM(ap.clicks) as 클릭수,
                        CASE WHEN SUM(ap.impressions) > 0
                             THEN ROUND(SUM(ap.clicks) * 100.0 / SUM(ap.impressions), 2)
                             ELSE 0 END as "CTR(%)",
                        SUM(ap.ad_spend) as 광고비,
                        SUM(ap.total_orders) as 주문수,
                        SUM(ap.total_revenue) as 매출,
                        CASE WHEN SUM(ap.ad_spend) > 0
                             THEN ROUND(SUM(ap.total_revenue) * 100.0 / SUM(ap.ad_spend), 1)
                             ELSE 0 END as "ROAS(%)"
                    FROM ad_performances ap
                    WHERE ap.account_id = :aid AND ap.ad_date >= :start
                        AND ap.report_type = 'keyword'
                        AND ap.keyword != ''
                    GROUP BY ap.keyword, ap.match_type
                    ORDER BY 매출 DESC
                """), conn, params={"aid": account_id, "start": start.isoformat()})
            return df
        except Exception:
            return pd.DataFrame()

    # ══════════════════════════════════════
    # 인사이트
    # ══════════════════════════════════════
    def get_insights(self, account_id: int, period_days: int = 14) -> List[str]:
        """자연어 인사이트 문장 생성"""
        insights = []
        today = date.today()
        period_start = today - timedelta(days=period_days)
        prev_start = period_start - timedelta(days=period_days)

        # 매출 트렌드
        with self.engine.connect() as conn:
            rev = conn.execute(text("""
                SELECT
                    COALESCE(SUM(CASE WHEN recognition_date >= :ps AND sale_type='SALE'
                                      THEN sale_amount ELSE 0 END), 0) as curr,
                    COALESCE(SUM(CASE WHEN recognition_date < :ps
                                      AND recognition_date >= :pvs
                                      AND sale_type='SALE'
                                      THEN sale_amount ELSE 0 END), 0) as prev,
                    COALESCE(SUM(CASE WHEN recognition_date >= :ps AND sale_type='SALE'
                                      THEN quantity ELSE 0 END), 0) as curr_qty
                FROM revenue_history
                WHERE account_id = :aid AND recognition_date >= :pvs
            """), {
                "aid": account_id,
                "ps": period_start.isoformat(),
                "pvs": prev_start.isoformat(),
            }).mappings().first()

        if rev:
            curr_rev = rev["curr"]
            prev_rev = rev["prev"]
            curr_qty = rev["curr_qty"]

            if curr_rev > 0:
                if prev_rev > 0:
                    change = (curr_rev - prev_rev) / prev_rev * 100
                    direction = "성장" if change > 0 else "감소"
                    insights.append(
                        f"최근 {period_days}일간 매출 ₩{curr_rev:,} "
                        f"(전기간 대비 {abs(change):.0f}% {direction})"
                    )
                else:
                    insights.append(f"최근 {period_days}일간 매출 ₩{curr_rev:,} ({curr_qty}건 판매)")

        # 재고 경고
        with self.engine.connect() as conn:
            stock_warn = conn.execute(text("""
                SELECT
                    SUM(CASE WHEN stock_quantity = 0 THEN 1 ELSE 0 END) as oos,
                    SUM(CASE WHEN stock_quantity BETWEEN 1 AND 5 THEN 1 ELSE 0 END) as low,
                    COUNT(*) as total
                FROM listings
                WHERE account_id = :aid AND coupang_status = 'active'
            """), {"aid": account_id}).mappings().first()

        if stock_warn:
            oos = stock_warn["oos"] or 0
            low = stock_warn["low"] or 0
            if oos > 0:
                insights.append(f"품절 상품 {oos}개 — 즉시 재고 보충 필요 (알고리즘 페널티 발생)")
            if low > 0:
                insights.append(f"재고 부족(1~5개) 상품 {low}개 — 품절 전 보충 권장")

        # 광고 요약
        ad_summary = self.get_ad_summary(account_id, period_days)
        if ad_summary["has_data"]:
            roas = ad_summary["roas"]
            spend = ad_summary["total_spend"]
            insights.append(
                f"광고 ROAS {roas:.0f}% — 광고비 ₩{spend:,} 투입, "
                f"매출 ₩{ad_summary['total_revenue']:,} 발생"
            )

        # 배송 정책
        with self.engine.connect() as conn:
            ship = conn.execute(text("""
                SELECT
                    SUM(CASE WHEN delivery_charge_type = 'FREE' THEN 1 ELSE 0 END) as free_cnt,
                    SUM(CASE WHEN delivery_charge_type = 'NOT_FREE' THEN 1 ELSE 0 END) as paid_cnt,
                    COUNT(*) as total
                FROM listings
                WHERE account_id = :aid AND coupang_status = 'active'
            """), {"aid": account_id}).mappings().first()

        if ship and (ship["paid_cnt"] or 0) > 0:
            paid = ship["paid_cnt"]
            total = ship["total"]
            insights.append(f"유료배송 상품 {paid}/{total}개 — 무료배송 전환 시 노출 개선 기대")

        if not insights:
            insights.append("분석할 데이터가 충분하지 않습니다. 매출/광고 데이터가 쌓이면 인사이트가 생성됩니다.")

        return insights
