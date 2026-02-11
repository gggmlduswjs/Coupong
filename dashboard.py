"""
쿠팡 도서 자동화 대시보드
=========================
계정별 상품 관리 + API 등록 기능
실행: streamlit run dashboard.py
"""
import sys
import streamlit as st
from pathlib import Path
import logging

# 프로젝트 루트를 path에 추가
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO)

# ─── 페이지 설정 ───
st.set_page_config(page_title="쿠팡 도서 자동화", page_icon="📚", layout="wide")

# ─── 공통 유틸 ───
from app.dashboard_utils import query_df

# ─── 사이드바 ───
st.sidebar.title("📚 쿠팡 도서 자동화")

accounts_df = query_df("""
    SELECT id, account_name, vendor_id, wing_api_enabled,
           wing_access_key, wing_secret_key,
           outbound_shipping_code, return_center_code
    FROM accounts WHERE is_active = true ORDER BY account_name
""")
account_names = accounts_df["account_name"].tolist() if not accounts_df.empty else []

selected_account_name = st.sidebar.selectbox("계정 선택", account_names, index=0 if account_names else None)

selected_account = None
if selected_account_name and not accounts_df.empty:
    mask = accounts_df["account_name"] == selected_account_name
    if mask.any():
        selected_account = accounts_df[mask].iloc[0]

st.sidebar.divider()
page = st.sidebar.radio("메뉴", ["주문/배송", "상품", "매출/정산", "광고", "반품"])

if selected_account is not None:
    st.sidebar.divider()
    st.sidebar.caption("계정 정보")
    st.sidebar.text(f"Vendor: {selected_account.get('vendor_id', '-')}")
    st.sidebar.text(f"출고지: {selected_account.get('outbound_shipping_code', '-')}")
    st.sidebar.text(f"반품지: {selected_account.get('return_center_code', '-')}")


# ─── 페이지 라우팅 ───
if page == "주문/배송":
    from app.pages.orders import render
    render(selected_account, accounts_df, account_names)

elif page == "상품":
    from app.pages.products import render
    render(selected_account, accounts_df, account_names)

elif page == "매출/정산":
    from app.pages.profit import render
    render(selected_account, accounts_df, account_names)

elif page == "광고":
    from app.pages.ads import render
    render(selected_account, accounts_df, account_names)

elif page == "반품":
    from app.pages.returns import render
    render(selected_account, accounts_df, account_names)


st.sidebar.divider()
st.sidebar.caption("v6.0 | 모듈 분할 리팩토링")
