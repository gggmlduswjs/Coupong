"""전체 상품 관리 페이지"""
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import SessionLocal
from app.models.product import Product
from app.models.book import Book

st.set_page_config(
    page_title="상품 관리",
    page_icon="📦",
    layout="wide"
)

st.title("📦 전체 상품 관리")


def get_db():
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


db = get_db()

try:
    # =============================================
    # 마진 분석 요약
    # =============================================
    st.header("💰 마진 분석 요약")

    total_products = db.query(Product).count()
    ready_count = db.query(Product).filter(Product.status == 'ready').count()
    uploaded_count = db.query(Product).filter(Product.status == 'uploaded').count()
    excluded_count = db.query(Product).filter(Product.status == 'excluded').count()

    free_shipping = db.query(Product).filter(Product.shipping_policy == 'free').count()
    paid_shipping = db.query(Product).filter(Product.shipping_policy == 'paid').count()
    bundle_required = db.query(Product).filter(Product.shipping_policy == 'bundle_required').count()

    # 상태별 메트릭
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("전체 상품", f"{total_products:,}개")
    with col2:
        st.metric("대기 (ready)", f"{ready_count:,}개")
    with col3:
        st.metric("업로드 완료", f"{uploaded_count:,}개")
    with col4:
        st.metric("제외됨", f"{excluded_count:,}개")

    # 배송정책별 메트릭
    st.subheader("배송정책별 분포")
    ship_col1, ship_col2, ship_col3 = st.columns(3)
    with ship_col1:
        pct = (free_shipping / total_products * 100) if total_products else 0
        st.metric("무료배송", f"{free_shipping:,}개", f"{pct:.1f}%")
    with ship_col2:
        pct = (paid_shipping / total_products * 100) if total_products else 0
        st.metric("유료배송", f"{paid_shipping:,}개", f"{pct:.1f}%")
    with ship_col3:
        pct = (bundle_required / total_products * 100) if total_products else 0
        st.metric("묶음필요", f"{bundle_required:,}개", f"{pct:.1f}%")

    st.divider()

    # =============================================
    # 필터
    # =============================================
    st.header("🔍 상품 목록")

    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:
        status_filter = st.selectbox(
            "상태",
            ['전체', 'ready', 'uploaded', 'excluded']
        )

    with filter_col2:
        shipping_filter = st.selectbox(
            "배송정책",
            ['전체', 'free', 'paid', 'bundle_required']
        )

    with filter_col3:
        search = st.text_input("ISBN/상품명 검색", placeholder="검색어 입력...")

    # =============================================
    # 상품 조회
    # =============================================
    query = db.query(Product).join(Book, Product.book_id == Book.id)

    if status_filter != '전체':
        query = query.filter(Product.status == status_filter)
    if shipping_filter != '전체':
        query = query.filter(Product.shipping_policy == shipping_filter)
    if search:
        q = f"%{search}%"
        query = query.filter(
            (Product.isbn.like(q)) | (Book.title.like(q))
        )

    products = query.order_by(Product.net_margin.desc()).all()

    if not products:
        st.info("조건에 맞는 상품이 없습니다.")
    else:
        st.caption(f"총 {len(products):,}개 상품")

        # 테이블 데이터 구성
        rows = []
        for product in products:
            book = db.query(Book).filter(Book.id == product.book_id).first()
            rows.append({
                'ISBN': product.isbn,
                '상품명': book.title[:50] if book else '-',
                '정가': product.list_price,
                '판매가': product.sale_price,
                '순마진': product.net_margin,
                '배송정책': product.shipping_policy,
                '상태': product.status,
                '출판사': book.publisher_name if book else '-',
                '제외사유': product.exclude_reason or '',
            })

        df = pd.DataFrame(rows)

        # 가격 포맷
        for col_name in ['정가', '판매가', '순마진']:
            df[col_name] = df[col_name].apply(lambda x: f"{x:,}원")

        st.dataframe(df, width="stretch", hide_index=True, height=500)

        # =============================================
        # 개별 상품 제외/포함 토글
        # =============================================
        st.subheader("상품 상태 변경")

        toggle_col1, toggle_col2 = st.columns(2)

        with toggle_col1:
            isbn_input = st.text_input("ISBN 입력", placeholder="상태를 변경할 ISBN")

        with toggle_col2:
            new_status = st.selectbox("변경할 상태", ['ready', 'excluded'])

        if st.button("상태 변경", type="primary"):
            if isbn_input:
                target = db.query(Product).filter(Product.isbn == isbn_input).first()
                if target:
                    old_status = target.status
                    target.status = new_status
                    if new_status == 'excluded' and not target.exclude_reason:
                        target.exclude_reason = "수동 제외"
                    elif new_status == 'ready':
                        target.exclude_reason = None
                    db.commit()
                    st.success(f"[{isbn_input}] {old_status} → {new_status} 변경 완료")
                    st.rerun()
                else:
                    st.error(f"ISBN '{isbn_input}' 상품을 찾을 수 없습니다.")
            else:
                st.warning("ISBN을 입력하세요.")

finally:
    db.close()
