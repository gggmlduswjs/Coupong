"""계정별 상세 현황 페이지"""
import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path
from datetime import datetime
from collections import Counter
import sys

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import SessionLocal
from app.models.account import Account
from app.models.listing import Listing
from app.models.product import Product
from app.models.book import Book

st.set_page_config(
    page_title="계정 현황",
    page_icon="📊",
    layout="wide"
)

st.title("📊 계정별 상세 현황")


def get_db():
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


db = get_db()

try:
    accounts = db.query(Account).filter(Account.is_active == True).all()

    if not accounts:
        st.warning("등록된 활성 계정이 없습니다.")
        st.stop()

    # 계정 선택
    account_names = [a.account_name for a in accounts]
    selected_name = st.selectbox("계정 선택", account_names)
    selected_account = next(a for a in accounts if a.account_name == selected_name)

    # 해당 계정의 모든 listings 조회
    listings = db.query(Listing).filter(
        Listing.account_id == selected_account.id
    ).all()

    st.metric("총 등록 상품", f"{len(listings):,}개")

    if not listings:
        st.info("이 계정에 등록된 상품이 없습니다.")
        st.stop()

    # listings에서 상세 정보 수집
    listing_details = []
    publishers = []
    shipping_policies = []
    upload_months = []

    for listing in listings:
        book = None
        publisher_name = "-"

        if listing.product_id:
            product = db.query(Product).filter(Product.id == listing.product_id).first()
            if product:
                book = db.query(Book).filter(Book.id == product.book_id).first()

        if book and book.publisher:
            publisher_name = book.publisher.name or "기타"

        publishers.append(publisher_name)
        shipping_policies.append(listing.delivery_charge_type or "unknown")

        if listing.synced_at:
            upload_months.append(listing.synced_at.strftime("%Y-%m"))

        listing_details.append({
            'ISBN': listing.isbn or '-',
            '상품명': book.title[:50] if book else (listing.product_name or '-')[:50],
            '판매가': listing.sale_price,
            '배송유형': listing.delivery_charge_type or '-',
            '상태': listing.coupang_status,
            '출판사': publisher_name,
            '동기화일': listing.synced_at.strftime("%Y-%m-%d") if listing.synced_at else '-',
        })

    # =============================================
    # 차트 섹션
    # =============================================
    chart_col1, chart_col2 = st.columns(2)

    # 출판사별 분포
    with chart_col1:
        st.subheader("출판사별 분포")
        pub_counts = Counter(publishers)
        if pub_counts:
            pub_df = pd.DataFrame(
                pub_counts.most_common(15),
                columns=['출판사', '상품수']
            )
            fig = px.bar(
                pub_df, x='출판사', y='상품수',
                title=f"출판사별 등록 상품 (상위 15개)",
                color='상품수',
                color_continuous_scale='Blues'
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, width="stretch")

    # 배송유형별 분포
    with chart_col2:
        st.subheader("배송유형별 분포")
        ship_counts = Counter(shipping_policies)
        if ship_counts:
            ship_df = pd.DataFrame(
                list(ship_counts.items()),
                columns=['배송유형', '상품수']
            )
            fig = px.pie(
                ship_df, names='배송유형', values='상품수',
                title="배송유형별 비율",
                color_discrete_sequence=px.colors.qualitative.Set2
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, width="stretch")

    # 월별 동기화 추이
    st.subheader("월별 동기화 추이")
    if upload_months:
        month_counts = Counter(upload_months)
        month_df = pd.DataFrame(
            sorted(month_counts.items()),
            columns=['월', '동기화수']
        )
        fig = px.line(
            month_df, x='월', y='동기화수',
            title="월별 상품 동기화 추이",
            markers=True
        )
        fig.update_layout(height=350)
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("동기화 데이터가 없습니다.")

    # =============================================
    # 상세 테이블
    # =============================================
    st.subheader("전체 등록 상품 목록")

    # 필터
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        search = st.text_input("검색 (ISBN/상품명)", key="detail_search")
    with filter_col2:
        pub_filter = st.selectbox(
            "출판사",
            ['전체'] + sorted(set(publishers)),
            key="pub_filter"
        )
    with filter_col3:
        ship_filter = st.selectbox(
            "배송유형",
            ['전체', 'FREE', 'NOT_FREE', 'CONDITIONAL_FREE'],
            key="ship_detail_filter"
        )

    # 필터 적용
    filtered = listing_details
    if search:
        q = search.lower()
        filtered = [r for r in filtered if q in r['ISBN'].lower() or q in r['상품명'].lower()]
    if pub_filter != '전체':
        filtered = [r for r in filtered if r['출판사'] == pub_filter]
    if ship_filter != '전체':
        filtered = [r for r in filtered if r['배송유형'] == ship_filter]

    if filtered:
        df = pd.DataFrame(filtered)
        df['판매가'] = df['판매가'].apply(lambda x: f"{x:,}원")
        st.dataframe(df, width="stretch", hide_index=True)
        st.caption(f"총 {len(filtered):,}개 상품")
    else:
        st.info("조건에 맞는 상품이 없습니다.")

finally:
    db.close()
