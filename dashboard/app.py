"""쿠팡 자동화 대시보드 - 메인 페이지"""
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.database import SessionLocal
from app.models.account import Account
from app.models.listing import Listing
from app.models.product import Product
from app.models.book import Book
from uploaders.coupang_csv_generator import CoupangCSVGenerator

st.set_page_config(
    page_title="쿠팡 자동화 대시보드",
    page_icon="🏠",
    layout="wide"
)

st.title("🏠 쿠팡 자동화 대시보드")


def get_db():
    """DB 세션 생성"""
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


def get_account_stats(db):
    """계정별 통계 조회"""
    accounts = db.query(Account).filter(Account.is_active == True).all()
    stats = []

    for account in accounts:
        # 등록 완료 수
        registered_count = db.query(Listing).filter(
            Listing.account_id == account.id
        ).count()

        # 마지막 업로드 시간
        last_listing = db.query(Listing).filter(
            Listing.account_id == account.id
        ).order_by(Listing.synced_at.desc().nullslast()).first()
        last_upload = last_listing.synced_at if last_listing else None

        # 신규 대기 상품 수 (ready 상태 + 단권 업로드 가능 + 아직 listing 없음)
        registered_isbns_stmt = select(Listing.isbn).where(
            Listing.account_id == account.id
        )

        pending_count = db.query(Product).filter(
            Product.status == 'ready',
            Product.can_upload_single == True,
            ~Product.isbn.in_(registered_isbns_stmt)
        ).count()

        stats.append({
            'account': account,
            'registered_count': registered_count,
            'pending_count': pending_count,
            'last_upload': last_upload,
        })

    return stats


def get_pending_products(db, account_id):
    """계정별 대기 상품 조회"""
    registered_isbns_stmt = select(Listing.isbn).where(
        Listing.account_id == account_id
    )

    products = db.query(Product).join(Book, Product.book_id == Book.id).filter(
        Product.status == 'ready',
        Product.can_upload_single == True,
        ~Product.isbn.in_(registered_isbns_stmt)
    ).all()

    return products


def get_registered_listings(db, account_id):
    """계정별 등록 완료 listing 조회"""
    listings = db.query(Listing).filter(
        Listing.account_id == account_id
    ).order_by(Listing.synced_at.desc().nullslast()).all()

    return listings


def products_to_csv_data(products, db):
    """Product 리스트를 CSV Generator용 dict 리스트로 변환"""
    csv_data = []
    for product in products:
        book = db.query(Book).filter(Book.id == product.book_id).first()
        if not book:
            continue
        csv_data.append({
            'product_name': book.title,
            'isbn': product.isbn,
            'sale_price': product.sale_price,
            'original_price': product.list_price,
            'publisher': book.publisher.name if book.publisher else '',
            'author': '',
            'main_image_url': '',
            'description': '',
        })
    return csv_data


# ─────────────────────────────────────────────
# 메인 화면
# ─────────────────────────────────────────────

db = get_db()

try:
    account_stats = get_account_stats(db)

    # =============================================
    # A. 전체 현황 요약
    # =============================================
    st.header("📊 전체 현황 요약")

    if not account_stats:
        st.warning("등록된 활성 계정이 없습니다.")
    else:
        cols = st.columns(len(account_stats))
        for i, stat in enumerate(account_stats):
            with cols[i]:
                account = stat['account']
                last_upload_str = stat['last_upload'].strftime("%m/%d %H:%M") if stat['last_upload'] else "-"

                st.metric(
                    label=account.account_name,
                    value=f"등록: {stat['registered_count']:,}개",
                    delta=f"대기: {stat['pending_count']}개"
                )
                st.caption(f"최근 업로드: {last_upload_str}")

    # =============================================
    # B. 계정별 상세 탭
    # =============================================
    st.header("📋 계정별 상세")

    if account_stats:
        tab_names = [s['account'].account_name for s in account_stats]
        tabs = st.tabs(tab_names)

        for tab_idx, tab in enumerate(tabs):
            with tab:
                account = account_stats[tab_idx]['account']

                # 필터/검색
                filter_col1, filter_col2 = st.columns(2)
                with filter_col1:
                    search_query = st.text_input(
                        "ISBN/상품명 검색",
                        key=f"search_{account.id}",
                        placeholder="ISBN 또는 상품명 입력..."
                    )
                with filter_col2:
                    shipping_filter = st.selectbox(
                        "배송유형",
                        ['전체', 'FREE', 'NOT_FREE', 'CONDITIONAL_FREE'],
                        key=f"ship_filter_{account.id}"
                    )

                # 등록 완료 상품
                st.subheader("✅ 등록 완료 상품")
                listings = get_registered_listings(db, account.id)

                if listings:
                    listing_rows = []
                    for listing in listings:
                        # 필터 적용
                        if shipping_filter != '전체' and listing.delivery_charge_type != shipping_filter:
                            continue

                        book = None
                        if listing.product_id:
                            product = db.query(Product).filter(Product.id == listing.product_id).first()
                            if product:
                                book = db.query(Book).filter(Book.id == product.book_id).first()

                        title = book.title if book else (listing.product_name or "-")
                        publisher = (book.publisher.name if book and book.publisher else "-")

                        # 검색 필터
                        if search_query:
                            q = search_query.lower()
                            if q not in (listing.isbn or '').lower() and q not in title.lower():
                                continue

                        listing_rows.append({
                            'ISBN': listing.isbn or '-',
                            '상품명': title[:50],
                            '판매가': f"{listing.sale_price:,}원",
                            '배송유형': listing.delivery_charge_type or '-',
                            '동기화일': listing.synced_at.strftime("%Y-%m-%d") if listing.synced_at else '-',
                        })

                    if listing_rows:
                        st.dataframe(pd.DataFrame(listing_rows), width="stretch", hide_index=True)
                    else:
                        st.info("필터 조건에 맞는 상품이 없습니다.")
                else:
                    st.info("등록된 상품이 없습니다.")

                # 신규 대기 상품
                st.subheader("⏳ 신규 대기 상품")
                pending = get_pending_products(db, account.id)

                if pending:
                    pending_rows = []
                    for product in pending:
                        book = db.query(Book).filter(Book.id == product.book_id).first()
                        title = book.title if book else "-"
                        publisher = (book.publisher.name if book and book.publisher else "-")

                        # 필터
                        if search_query:
                            q = search_query.lower()
                            if q not in product.isbn.lower() and q not in title.lower():
                                continue

                        pending_rows.append({
                            'ISBN': product.isbn,
                            '상품명': title[:50],
                            '판매가': f"{product.sale_price:,}원",
                            '순마진': f"{product.net_margin:,}원",
                            '배송정책': product.shipping_policy,
                            '출판사': publisher,
                        })

                    if pending_rows:
                        st.dataframe(pd.DataFrame(pending_rows), width="stretch", hide_index=True)
                    else:
                        st.info("필터 조건에 맞는 대기 상품이 없습니다.")
                else:
                    st.info("대기 중인 상품이 없습니다.")

    # =============================================
    # C. 업로드 실행 패널
    # =============================================
    st.header("🚀 업로드 실행")

    if account_stats:
        # 계정 선택 (체크박스)
        st.subheader("계정 선택")
        selected_accounts = []
        check_cols = st.columns(len(account_stats))
        for i, stat in enumerate(account_stats):
            with check_cols[i]:
                if st.checkbox(
                    stat['account'].account_name,
                    value=True,
                    key=f"upload_check_{stat['account'].id}"
                ):
                    selected_accounts.append(stat['account'])

        if not selected_accounts:
            st.warning("업로드할 계정을 선택하세요.")
        else:
            # CSV 생성 & 미리보기
            if st.button("📄 CSV 생성 & 미리보기", type="primary"):
                generator = CoupangCSVGenerator()

                for account in selected_accounts:
                    pending = get_pending_products(db, account.id)
                    if not pending:
                        st.info(f"[{account.account_name}] 대기 상품 없음")
                        continue

                    csv_data = products_to_csv_data(pending, db)

                    # 미리보기 테이블
                    st.subheader(f"📦 {account.account_name} - {len(csv_data)}개 상품")
                    preview_rows = []
                    for item in csv_data:
                        preview_rows.append({
                            'ISBN': item['isbn'],
                            '상품명': item['product_name'][:40],
                            '판매가': f"{item['sale_price']:,}원",
                            '정가': f"{item['original_price']:,}원",
                            '출판사': item['publisher'],
                        })
                    st.dataframe(pd.DataFrame(preview_rows), width="stretch", hide_index=True)

                    # CSV 파일 생성
                    filepath = generator.generate_csv(csv_data, account.account_name)

                    # 세션에 저장
                    if 'generated_csvs' not in st.session_state:
                        st.session_state.generated_csvs = {}
                    st.session_state.generated_csvs[account.account_name] = {
                        'filepath': filepath,
                        'count': len(csv_data),
                    }

                    st.success(f"CSV 생성 완료: {filepath}")

            # CSV 다운로드 버튼
            if 'generated_csvs' in st.session_state and st.session_state.generated_csvs:
                st.subheader("📥 CSV 다운로드")
                for acc_name, csv_info in st.session_state.generated_csvs.items():
                    filepath = Path(csv_info['filepath'])
                    if filepath.exists():
                        with open(filepath, 'rb') as f:
                            csv_bytes = f.read()
                        st.download_button(
                            label=f"⬇️ {acc_name} CSV 다운로드 ({csv_info['count']}개)",
                            data=csv_bytes,
                            file_name=filepath.name,
                            mime="text/csv",
                            key=f"dl_{acc_name}"
                        )

            # 쿠팡 자동 업로드 버튼
            st.subheader("🤖 자동 업로드")
            st.warning("Playwright를 이용한 자동 업로드는 CSV 생성 후 실행하세요.")

            if st.button("🚀 쿠팡 자동 업로드", type="secondary"):
                if 'generated_csvs' not in st.session_state or not st.session_state.generated_csvs:
                    st.error("먼저 CSV를 생성하세요.")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    total = len(st.session_state.generated_csvs)
                    for idx, (acc_name, csv_info) in enumerate(st.session_state.generated_csvs.items()):
                        status_text.text(f"업로드 중: {acc_name} ({idx + 1}/{total})")
                        progress_bar.progress((idx + 1) / total)

                        # TODO: Playwright 업로드 로직 연동
                        st.info(f"[{acc_name}] Playwright 업로드 - 구현 예정")

                    status_text.text("업로드 완료!")
                    st.success("모든 계정 업로드가 완료되었습니다.")

finally:
    db.close()
