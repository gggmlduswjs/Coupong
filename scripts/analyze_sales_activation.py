"""
매출 활성화 전략 — DB 기반 현황 분석 리포트
==========================================
5개 쿠팡 계정 DB 데이터로 매출 차이 원인 진단.
터미널 출력 + (선택) Obsidian 노트 저장.

사용법:
    python scripts/analyze_sales_activation.py              # 터미널 출력만
    python scripts/analyze_sales_activation.py --save       # Obsidian 노트에도 저장
    python scripts/analyze_sales_activation.py --months 6   # 최근 6개월 분석
"""
import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from collections import defaultdict

# Windows cp949 출력 인코딩 문제 방지
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import text

# 프로젝트 루트
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.database import get_engine_for_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class SalesActivationAnalyzer:
    """DB 기반 매출 활성화 분석 엔진"""

    def __init__(self, engine, months: int = 3):
        self.engine = engine
        self.months = months
        self.today = date.today()
        self.start_date = self.today - timedelta(days=months * 30)
        self.report_lines: list[str] = []
        self.actions: list[str] = []  # 실행 가능 액션 수집

    def _q(self, sql: str, params: dict = None) -> list[dict]:
        """SQL 실행 → dict 리스트"""
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params or {}).mappings().all()
        return [dict(r) for r in rows]

    def _print(self, line: str = ""):
        """터미널 + 리포트 버퍼에 동시 출력"""
        print(line)
        self.report_lines.append(line)

    def _section(self, num: int, title: str):
        """섹션 헤더"""
        self._print("")
        self._print(f"{'='*60}")
        self._print(f"  {num}. {title}")
        self._print(f"{'='*60}")

    def _table(self, headers: list[str], rows: list[list], alignments: list[str] = None):
        """간단 테이블 출력 (터미널용)"""
        if not rows:
            self._print("  (데이터 없음)")
            return

        # 컬럼 너비 계산
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))

        # 헤더
        header_line = "  " + " | ".join(
            str(h).ljust(col_widths[i]) if (not alignments or alignments[i] == 'l') else str(h).rjust(col_widths[i])
            for i, h in enumerate(headers)
        )
        self._print(header_line)
        self._print("  " + "-+-".join("-" * w for w in col_widths))

        # 데이터
        for row in rows:
            line = "  " + " | ".join(
                str(cell).ljust(col_widths[i]) if (not alignments or alignments[i] == 'l') else str(cell).rjust(col_widths[i])
                for i, cell in enumerate(row)
            )
            self._print(line)

    @staticmethod
    def _fmt_won(amount) -> str:
        """금액 포맷 (만원 단위)"""
        if amount is None:
            return "0"
        if abs(amount) >= 10000:
            return f"{amount/10000:,.1f}만"
        return f"{amount:,}"

    @staticmethod
    def _fmt_pct(value) -> str:
        """퍼센트 포맷"""
        if value is None:
            return "0.0%"
        return f"{value:.1f}%"

    # ──────────────── 1. 계정별 매출 현황 ────────────────

    def analyze_revenue_by_account(self):
        """계정별 매출 현황 + 월별 추이"""
        self._section(1, "계정별 매출 현황")

        # 전체 기간 집계
        rows = self._q("""
            SELECT a.account_name,
                   COUNT(DISTINCT rh.order_id) AS order_cnt,
                   SUM(CASE WHEN rh.sale_type='SALE' THEN rh.sale_amount ELSE -rh.sale_amount END) AS total_revenue,
                   SUM(CASE WHEN rh.sale_type='SALE' THEN rh.quantity ELSE 0 END) AS total_qty,
                   ROUND(AVG(CASE WHEN rh.sale_type='SALE' THEN rh.sale_price ELSE NULL END)) AS avg_price
            FROM revenue_history rh
            JOIN accounts a ON a.id = rh.account_id
            WHERE rh.sale_date >= :start
            GROUP BY a.account_name
            ORDER BY total_revenue DESC
        """, {"start": str(self.start_date)})

        if not rows:
            self._print("  매출 데이터 없음")
            return

        total_revenue = sum(r["total_revenue"] or 0 for r in rows)

        self._print(f"\n  기간: {self.start_date} ~ {self.today} (최근 {self.months}개월)")
        self._print(f"  총 매출: {self._fmt_won(total_revenue)}원\n")

        table_rows = []
        for r in rows:
            rev = r["total_revenue"] or 0
            share = (rev / total_revenue * 100) if total_revenue else 0
            table_rows.append([
                r["account_name"],
                self._fmt_won(rev) + "원",
                f"{r['order_cnt']:,}건",
                f"{r['total_qty'] or 0:,}권",
                self._fmt_won(r['avg_price'] or 0) + "원",
                self._fmt_pct(share),
            ])
        self._table(
            ["계정", "매출", "주문", "판매량", "평균단가", "비중"],
            table_rows,
            ["l", "r", "r", "r", "r", "r"],
        )

        # 매출 편중 경고
        if rows and total_revenue > 0:
            top = rows[0]
            top_share = (top["total_revenue"] or 0) / total_revenue * 100
            if top_share > 60:
                self._print(f"\n  ⚠ 매출 편중: {top['account_name']}에 {top_share:.1f}% 집중")

        # 월별 추이
        self._print(f"\n  [월별 추이]")
        monthly = self._q("""
            SELECT a.account_name,
                   SUBSTR(CAST(rh.sale_date AS TEXT), 1, 7) AS month,
                   SUM(CASE WHEN rh.sale_type='SALE' THEN rh.sale_amount ELSE -rh.sale_amount END) AS revenue
            FROM revenue_history rh
            JOIN accounts a ON a.id = rh.account_id
            WHERE rh.sale_date >= :start
            GROUP BY a.account_name, month
            ORDER BY month, revenue DESC
        """, {"start": str(self.start_date)})

        # 피벗 (월 → 계정별 매출)
        months_set = sorted(set(r["month"] for r in monthly))
        accounts_set = sorted(set(r["account_name"] for r in monthly))
        pivot = {(r["account_name"], r["month"]): r["revenue"] for r in monthly}

        headers = ["계정"] + months_set
        table_rows = []
        for acct in accounts_set:
            row = [acct] + [self._fmt_won(pivot.get((acct, m), 0)) for m in months_set]
            table_rows.append(row)
        self._table(headers, table_rows, ["l"] + ["r"] * len(months_set))

    # ──────────────── 2. 배송비 정책 분포 ────────────────

    def analyze_shipping_policy(self):
        """계정별 배송비 정책 분포"""
        self._section(2, "계정별 배송비 정책 분포")

        rows = self._q("""
            SELECT a.account_name,
                   l.delivery_charge_type,
                   COUNT(*) AS cnt
            FROM listings l
            JOIN accounts a ON a.id = l.account_id
            WHERE l.coupang_status = 'active'
              AND l.delivery_charge_type IS NOT NULL
            GROUP BY a.account_name, l.delivery_charge_type
            ORDER BY a.account_name, l.delivery_charge_type
        """)

        if not rows:
            self._print("  배송비 데이터 없음")
            return

        # 계정별 집계
        acct_data: dict[str, dict] = defaultdict(lambda: {"FREE": 0, "NOT_FREE": 0, "CONDITIONAL_FREE": 0, "total": 0})
        for r in rows:
            dtype = r["delivery_charge_type"] or "UNKNOWN"
            acct_data[r["account_name"]][dtype] = r["cnt"]
            acct_data[r["account_name"]]["total"] += r["cnt"]

        table_rows = []
        for acct in sorted(acct_data):
            d = acct_data[acct]
            total = d["total"] or 1
            table_rows.append([
                acct,
                f"{d['FREE']:,} ({d['FREE']/total*100:.0f}%)",
                f"{d['CONDITIONAL_FREE']:,} ({d['CONDITIONAL_FREE']/total*100:.0f}%)",
                f"{d['NOT_FREE']:,} ({d['NOT_FREE']/total*100:.0f}%)",
                f"{total:,}",
            ])
        self._table(
            ["계정", "무료배송", "조건부무료", "유료배송", "합계"],
            table_rows,
            ["l", "r", "r", "r", "r"],
        )

        # 인사이트: 무료배송 비율과 매출 상관관계
        self._print("\n  [핵심 가설] 무료배송 비율이 높을수록 매출 유리?")
        for acct in sorted(acct_data):
            d = acct_data[acct]
            total = d["total"] or 1
            free_rate = d["FREE"] / total * 100
            self._print(f"    {acct}: 무료배송 {free_rate:.1f}%")

    # ──────────────── 3. 매출 상품 vs 미매출 상품 비교 ────────────────

    def analyze_sold_vs_unsold(self):
        """매출 발생 vs 미발생 상품 특성 비교"""
        self._section(3, "매출 상품 vs 미매출 상품 특성 비교")

        # 매출 발생 리스팅 ID 집합
        sold_stats = self._q("""
            SELECT
                l.delivery_charge_type,
                CASE
                    WHEN l.sale_price < 10000 THEN '~1만'
                    WHEN l.sale_price < 15000 THEN '1~1.5만'
                    WHEN l.sale_price < 20000 THEN '1.5~2만'
                    ELSE '2만+'
                END AS price_range,
                COUNT(DISTINCT l.id) AS cnt,
                AVG(l.sale_price) AS avg_price,
                'sold' AS category
            FROM listings l
            WHERE l.coupang_status = 'active'
              AND l.id IN (
                  SELECT DISTINCT listing_id FROM revenue_history
                  WHERE listing_id IS NOT NULL AND sale_type='SALE'
                    AND sale_date >= :start
              )
            GROUP BY l.delivery_charge_type, price_range
        """, {"start": str(self.start_date)})

        unsold_stats = self._q("""
            SELECT
                l.delivery_charge_type,
                CASE
                    WHEN l.sale_price < 10000 THEN '~1만'
                    WHEN l.sale_price < 15000 THEN '1~1.5만'
                    WHEN l.sale_price < 20000 THEN '1.5~2만'
                    ELSE '2만+'
                END AS price_range,
                COUNT(DISTINCT l.id) AS cnt,
                AVG(l.sale_price) AS avg_price,
                'unsold' AS category
            FROM listings l
            WHERE l.coupang_status = 'active'
              AND l.id NOT IN (
                  SELECT DISTINCT listing_id FROM revenue_history
                  WHERE listing_id IS NOT NULL AND sale_type='SALE'
                    AND sale_date >= :start
              )
            GROUP BY l.delivery_charge_type, price_range
        """, {"start": str(self.start_date)})

        # 배송비별 비교
        self._print("\n  [배송비 정책별 비교]")
        sold_by_ship = defaultdict(int)
        unsold_by_ship = defaultdict(int)
        for r in sold_stats:
            sold_by_ship[r["delivery_charge_type"]] += r["cnt"]
        for r in unsold_stats:
            unsold_by_ship[r["delivery_charge_type"]] += r["cnt"]

        all_types = sorted(set(list(sold_by_ship.keys()) + list(unsold_by_ship.keys())), key=lambda x: x or "ZZZ")
        table_rows = []
        for t in all_types:
            s = sold_by_ship.get(t, 0)
            u = unsold_by_ship.get(t, 0)
            total = s + u
            sold_rate = s / total * 100 if total else 0
            table_rows.append([t or "미설정", f"{s:,}", f"{u:,}", f"{total:,}", self._fmt_pct(sold_rate)])
        self._table(
            ["배송비 정책", "매출O", "매출X", "합계", "매출비율"],
            table_rows,
            ["l", "r", "r", "r", "r"],
        )

        # 가격대별 비교
        self._print("\n  [가격대별 비교]")
        sold_by_price = defaultdict(int)
        unsold_by_price = defaultdict(int)
        for r in sold_stats:
            sold_by_price[r["price_range"]] += r["cnt"]
        for r in unsold_stats:
            unsold_by_price[r["price_range"]] += r["cnt"]

        price_order = ["~1만", "1~1.5만", "1.5~2만", "2만+"]
        table_rows = []
        for p in price_order:
            s = sold_by_price.get(p, 0)
            u = unsold_by_price.get(p, 0)
            total = s + u
            sold_rate = s / total * 100 if total else 0
            table_rows.append([p, f"{s:,}", f"{u:,}", f"{total:,}", self._fmt_pct(sold_rate)])
        self._table(
            ["가격대", "매출O", "매출X", "합계", "매출비율"],
            table_rows,
            ["l", "r", "r", "r", "r"],
        )

    # ──────────────── 4. 품절 현황 ────────────────

    def analyze_stockout(self):
        """계정별 품절(재고 0) 현황"""
        self._section(4, "품절(재고 0) 현황")

        rows = self._q("""
            SELECT a.account_name,
                   SUM(CASE WHEN l.stock_quantity = 0 THEN 1 ELSE 0 END) AS oos_cnt,
                   COUNT(*) AS total_cnt,
                   SUM(CASE WHEN l.stock_quantity = 0
                        AND l.id IN (SELECT DISTINCT listing_id FROM revenue_history
                                     WHERE listing_id IS NOT NULL AND sale_type='SALE')
                        THEN 1 ELSE 0 END) AS oos_with_sales
            FROM listings l
            JOIN accounts a ON a.id = l.account_id
            WHERE l.coupang_status = 'active'
            GROUP BY a.account_name
            ORDER BY oos_cnt DESC
        """)

        table_rows = []
        total_oos_with_sales = 0
        for r in rows:
            oos = r["oos_cnt"] or 0
            total = r["total_cnt"] or 1
            oos_sales = r["oos_with_sales"] or 0
            total_oos_with_sales += oos_sales
            table_rows.append([
                r["account_name"],
                f"{oos:,}개",
                self._fmt_pct(oos / total * 100),
                f"{total:,}개",
                f"{oos_sales:,}개",
            ])
        self._table(
            ["계정", "품절", "품절률", "전체", "과거매출有"],
            table_rows,
            ["l", "r", "r", "r", "r"],
        )

        if total_oos_with_sales > 0:
            self._print(f"\n  ⚠ 과거 매출 이력 있는 품절 상품 {total_oos_with_sales}개 → 재고 리필 시 즉시 매출 복구 가능")
            self.actions.append(f"품절 상품 중 과거 매출 이력 {total_oos_with_sales}개 재고 리필 → 즉시 매출 복구")

        # 품절 상위 상품 (매출 이력 있는 것)
        oos_top = self._q("""
            SELECT a.account_name, l.product_name,
                   SUM(rh.sale_amount) AS past_revenue,
                   SUM(rh.quantity) AS past_qty
            FROM listings l
            JOIN accounts a ON a.id = l.account_id
            JOIN revenue_history rh ON rh.listing_id = l.id AND rh.sale_type = 'SALE'
            WHERE l.coupang_status = 'active' AND l.stock_quantity = 0
            GROUP BY a.account_name, l.product_name
            ORDER BY past_revenue DESC
            LIMIT 10
        """)

        if oos_top:
            self._print("\n  [과거매출 TOP 품절 상품]")
            table_rows = []
            for r in oos_top:
                table_rows.append([
                    r["account_name"],
                    (r["product_name"] or "")[:30],
                    self._fmt_won(r["past_revenue"]) + "원",
                    f"{r['past_qty']}권",
                ])
            self._table(["계정", "상품명", "과거매출", "판매량"], table_rows, ["l", "l", "r", "r"])

    # ──────────────── 5. 출판사(공급률) 믹스 비교 ────────────────

    def analyze_publisher_mix(self):
        """계정별 출판사 분포 + 평균 공급률"""
        self._section(5, "출판사(공급률) 믹스 비교")

        rows = self._q("""
            SELECT a.account_name,
                   b.publisher_name,
                   COUNT(*) AS listing_cnt,
                   AVG(p.supply_rate) AS avg_supply_rate,
                   AVG(p.net_margin) AS avg_margin
            FROM listings l
            JOIN accounts a ON a.id = l.account_id
            JOIN products p ON p.id = l.product_id
            JOIN books b ON b.id = p.book_id
            WHERE l.coupang_status = 'active' AND l.product_type = 'single'
            GROUP BY a.account_name, b.publisher_name
            ORDER BY a.account_name, listing_cnt DESC
        """)

        if not rows:
            self._print("  데이터 없음")
            return

        # 계정별 요약
        acct_summary = defaultdict(lambda: {"total": 0, "publishers": 0, "supply_sum": 0, "margin_sum": 0})
        acct_top_pub = defaultdict(list)  # 계정별 상위 출판사

        for r in rows:
            acct = r["account_name"]
            acct_summary[acct]["total"] += r["listing_cnt"]
            acct_summary[acct]["publishers"] += 1
            acct_summary[acct]["supply_sum"] += (r["avg_supply_rate"] or 0) * r["listing_cnt"]
            acct_summary[acct]["margin_sum"] += (r["avg_margin"] or 0) * r["listing_cnt"]
            if len(acct_top_pub[acct]) < 3:
                acct_top_pub[acct].append(f"{r['publisher_name']}({r['listing_cnt']})")

        self._print("\n  [계정별 요약]")
        table_rows = []
        for acct in sorted(acct_summary):
            d = acct_summary[acct]
            total = d["total"] or 1
            avg_supply = d["supply_sum"] / total * 100
            avg_margin = round(d["margin_sum"] / total)
            table_rows.append([
                acct,
                f"{d['publishers']}개",
                f"{total:,}개",
                f"{avg_supply:.1f}%",
                self._fmt_won(avg_margin) + "원",
                ", ".join(acct_top_pub[acct]),
            ])
        self._table(
            ["계정", "출판사수", "리스팅", "평균공급률", "평균마진", "상위 출판사"],
            table_rows,
            ["l", "r", "r", "r", "r", "l"],
        )

        # 매출 발생 출판사 vs 미발생 출판사
        self._print("\n  [매출 발생 출판사 TOP 10]")
        pub_revenue = self._q("""
            SELECT b.publisher_name,
                   COUNT(DISTINCT l.id) AS listing_cnt,
                   SUM(rh.sale_amount) AS total_revenue,
                   SUM(rh.quantity) AS total_qty,
                   AVG(p.supply_rate) AS avg_supply_rate
            FROM revenue_history rh
            JOIN listings l ON l.id = rh.listing_id
            JOIN products p ON p.id = l.product_id
            JOIN books b ON b.id = p.book_id
            WHERE rh.sale_type = 'SALE' AND rh.sale_date >= :start
            GROUP BY b.publisher_name
            ORDER BY total_revenue DESC
            LIMIT 10
        """, {"start": str(self.start_date)})

        if pub_revenue:
            table_rows = []
            for r in pub_revenue:
                table_rows.append([
                    r["publisher_name"],
                    f"{r['listing_cnt']:,}",
                    self._fmt_won(r["total_revenue"]) + "원",
                    f"{r['total_qty']}권",
                    f"{(r['avg_supply_rate'] or 0)*100:.0f}%",
                ])
            self._table(
                ["출판사", "리스팅", "매출", "판매량", "공급률"],
                table_rows,
                ["l", "r", "r", "r", "r"],
            )

    # ──────────────── 6. 가격대별 매출 분석 ────────────────

    def analyze_price_band_revenue(self):
        """가격대별 매출 분석 + 무료배송 전환 가능 식별"""
        self._section(6, "가격대별 매출 분석")

        rows = self._q("""
            SELECT
                CASE
                    WHEN l.sale_price < 5000 THEN '~5천'
                    WHEN l.sale_price < 10000 THEN '5천~1만'
                    WHEN l.sale_price < 15000 THEN '1~1.5만'
                    WHEN l.sale_price < 20000 THEN '1.5~2만'
                    WHEN l.sale_price < 30000 THEN '2~3만'
                    ELSE '3만+'
                END AS price_band,
                COUNT(DISTINCT l.id) AS listing_cnt,
                SUM(CASE WHEN rh.sale_type='SALE' THEN rh.sale_amount ELSE 0 END) AS revenue,
                SUM(CASE WHEN rh.sale_type='SALE' THEN rh.quantity ELSE 0 END) AS qty,
                l.delivery_charge_type
            FROM listings l
            LEFT JOIN revenue_history rh ON rh.listing_id = l.id
                AND rh.sale_date >= :start
            WHERE l.coupang_status = 'active'
            GROUP BY price_band, l.delivery_charge_type
            ORDER BY l.sale_price
        """, {"start": str(self.start_date)})

        if not rows:
            self._print("  데이터 없음")
            return

        # 가격대별 집계 (배송비 무관)
        band_data = defaultdict(lambda: {"cnt": 0, "revenue": 0, "qty": 0, "free": 0, "paid": 0})
        for r in rows:
            band = r["price_band"]
            band_data[band]["cnt"] += r["listing_cnt"]
            band_data[band]["revenue"] += r["revenue"] or 0
            band_data[band]["qty"] += r["qty"] or 0
            if r["delivery_charge_type"] == "FREE":
                band_data[band]["free"] += r["listing_cnt"]
            elif r["delivery_charge_type"] == "NOT_FREE":
                band_data[band]["paid"] += r["listing_cnt"]

        band_order = ["~5천", "5천~1만", "1~1.5만", "1.5~2만", "2~3만", "3만+"]
        total_rev = sum(d["revenue"] for d in band_data.values()) or 1

        table_rows = []
        for band in band_order:
            d = band_data.get(band, {"cnt": 0, "revenue": 0, "qty": 0, "free": 0, "paid": 0})
            total = d["cnt"] or 1
            table_rows.append([
                band,
                f"{d['cnt']:,}",
                self._fmt_won(d["revenue"]) + "원",
                self._fmt_pct(d["revenue"] / total_rev * 100),
                f"{d['qty']:,}권",
                f"{d['free']:,} ({d['free']/total*100:.0f}%)",
                f"{d['paid']:,}",
            ])
        self._table(
            ["가격대", "리스팅", "매출", "매출비중", "판매량", "무료배송", "유료배송"],
            table_rows,
            ["l", "r", "r", "r", "r", "r", "r"],
        )

        # 무료배송 전환 가능 상품 식별
        self._print("\n  [무료배송 전환 가능 상품]")
        switchable = self._q("""
            SELECT a.account_name,
                   COUNT(*) AS cnt,
                   AVG(l.sale_price) AS avg_price
            FROM listings l
            JOIN accounts a ON a.id = l.account_id
            WHERE l.coupang_status = 'active'
              AND l.delivery_charge_type = 'NOT_FREE'
              AND l.sale_price >= 15000
            GROUP BY a.account_name
            ORDER BY cnt DESC
        """)

        if switchable:
            total_switchable = sum(r["cnt"] for r in switchable)
            table_rows = []
            for r in switchable:
                table_rows.append([
                    r["account_name"],
                    f"{r['cnt']:,}개",
                    self._fmt_won(r["avg_price"]) + "원",
                ])
            self._table(["계정", "전환가능", "평균가격"], table_rows, ["l", "r", "r"])
            self._print(f"\n  → 유료배송이지만 정가 1.5만 이상인 상품 총 {total_switchable}개 → 무료배송 전환 검토")
            if total_switchable > 0:
                self.actions.append(f"유료배송 중 정가 1.5만+ 상품 {total_switchable}개 무료배송 전환 검토")
        else:
            self._print("  전환 가능 상품 없음")

    # ──────────────── 7. 실행 가능 액션 리스트 ────────────────

    def generate_action_items(self):
        """분석 결과 기반 실행 가능 액션 리스트"""
        self._section(7, "실행 가능 액션 리스트")

        # 추가 분석: 광고비 비교
        ad_data = self._q("""
            SELECT a.account_name,
                   SUM(ads.billable_cost) AS total_spend
            FROM ad_spends ads
            JOIN accounts a ON a.id = ads.account_id
            WHERE ads.ad_date >= :start
            GROUP BY a.account_name
            ORDER BY total_spend DESC
        """, {"start": str(self.start_date)})

        if ad_data:
            spending = {r["account_name"]: r["total_spend"] or 0 for r in ad_data}
            no_ad_accts = []

            # 매출 있는 계정 조회
            rev_accts = self._q("""
                SELECT a.account_name
                FROM revenue_history rh
                JOIN accounts a ON a.id = rh.account_id
                WHERE rh.sale_date >= :start AND rh.sale_type='SALE'
                GROUP BY a.account_name
                HAVING SUM(rh.sale_amount) < 500000
            """, {"start": str(self.start_date)})

            low_rev_names = [r["account_name"] for r in rev_accts]
            for acct in low_rev_names:
                if spending.get(acct, 0) == 0:
                    no_ad_accts.append(acct)

            if no_ad_accts:
                self.actions.append(f"광고 미집행 저매출 계정: {', '.join(no_ad_accts)} → 소액 광고 시작 검토")

        # 계정별 리스팅 수 불균형
        listing_counts = self._q("""
            SELECT a.account_name, COUNT(*) AS cnt
            FROM listings l
            JOIN accounts a ON a.id = l.account_id
            WHERE l.coupang_status = 'active'
            GROUP BY a.account_name
            ORDER BY cnt DESC
        """)
        if len(listing_counts) >= 2:
            max_cnt = listing_counts[0]["cnt"]
            for r in listing_counts[1:]:
                gap = max_cnt - r["cnt"]
                if gap > 100:
                    self.actions.append(
                        f"{r['account_name']} 리스팅 {r['cnt']:,}개 → {listing_counts[0]['account_name']}({max_cnt:,}개) 대비 {gap:,}개 부족"
                    )

        # 중복 상품 매출 차이 분석
        overlap_gap = self._q("""
            SELECT l1_acct, l2_acct, overlap_cnt, l1_rev, l2_rev
            FROM (
                SELECT a1.account_name AS l1_acct, a2.account_name AS l2_acct,
                       COUNT(*) AS overlap_cnt,
                       (SELECT COALESCE(SUM(rh.sale_amount),0) FROM revenue_history rh
                        WHERE rh.account_id = a1.id AND rh.sale_type='SALE' AND rh.sale_date >= :start) AS l1_rev,
                       (SELECT COALESCE(SUM(rh.sale_amount),0) FROM revenue_history rh
                        WHERE rh.account_id = a2.id AND rh.sale_type='SALE' AND rh.sale_date >= :start) AS l2_rev
                FROM listings l1
                JOIN listings l2 ON l1.isbn = l2.isbn AND l1.account_id < l2.account_id
                JOIN accounts a1 ON a1.id = l1.account_id
                JOIN accounts a2 ON a2.id = l2.account_id
                WHERE l1.coupang_status = 'active' AND l2.coupang_status = 'active'
                  AND l1.isbn IS NOT NULL
                GROUP BY a1.account_name, a2.account_name
                HAVING overlap_cnt > 100
            )
            WHERE l1_rev > l2_rev * 5
            ORDER BY l1_rev - l2_rev DESC
            LIMIT 3
        """, {"start": str(self.start_date)})

        for r in overlap_gap:
            self.actions.append(
                f"{r['l1_acct']}({self._fmt_won(r['l1_rev'])}) vs {r['l2_acct']}({self._fmt_won(r['l2_rev'])}) — "
                f"공유 상품 {r['overlap_cnt']:,}개인데 매출 {r['l1_rev']//(r['l2_rev'] or 1)}배 차이 → {r['l2_acct']} 노출/광고 강화"
            )

        # 액션 출력
        if not self.actions:
            self._print("\n  특별한 액션 항목 없음")
            return

        self._print(f"\n  총 {len(self.actions)}개 액션 항목:\n")
        for i, action in enumerate(self.actions, 1):
            self._print(f"  {i}. {action}")

    # ──────────────── 전체 실행 ────────────────

    def run(self) -> str:
        """전체 분석 실행"""
        self._print("=" * 60)
        self._print("  매출 활성화 전략 — DB 기반 현황 분석 리포트")
        self._print(f"  분석일: {self.today}  |  기간: 최근 {self.months}개월")
        self._print("=" * 60)

        self.analyze_revenue_by_account()
        self.analyze_shipping_policy()
        self.analyze_sold_vs_unsold()
        self.analyze_stockout()
        self.analyze_publisher_mix()
        self.analyze_price_band_revenue()
        self.generate_action_items()

        self._print("\n" + "=" * 60)
        self._print("  분석 완료")
        self._print("=" * 60)

        return "\n".join(self.report_lines)

    def save_to_obsidian(self, report: str):
        """Obsidian 노트에 저장 (G: 직접)"""
        def _vault_dir():
            env = ROOT / ".env"
            if env.exists():
                for line in env.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("OBSIDIAN_VAULT_PATH="):
                        v = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if v:
                            return Path(v) / "10. project" / "Coupong" / "03-Technical"
            return ROOT / "obsidian_vault" / "10. project" / "Coupong" / "03-Technical"

        vault_dir = _vault_dir()
        vault_dir.mkdir(parents=True, exist_ok=True)

        filename = f"매출활성화-분석리포트-{self.today}.md"
        filepath = vault_dir / filename

        md_content = f"# 매출 활성화 분석 리포트\n\n"
        md_content += f"#analysis #sales #strategy\n\n"
        md_content += f"**분석일:** {self.today}\n"
        md_content += f"**기간:** 최근 {self.months}개월 ({self.start_date} ~ {self.today})\n\n"
        md_content += "---\n\n"
        md_content += "```\n"
        md_content += report
        md_content += "\n```\n"

        filepath.write_text(md_content, encoding="utf-8")
        print(f"\n✅ Obsidian 노트 저장: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="매출 활성화 전략 DB 분석")
    parser.add_argument("--months", type=int, default=3, help="분석 기간 (개월, 기본 3)")
    parser.add_argument("--save", action="store_true", help="Obsidian 노트에 저장")
    args = parser.parse_args()

    engine = get_engine_for_db()
    analyzer = SalesActivationAnalyzer(engine, months=args.months)
    report = analyzer.run()

    if args.save:
        analyzer.save_to_obsidian(report)


if __name__ == "__main__":
    main()
