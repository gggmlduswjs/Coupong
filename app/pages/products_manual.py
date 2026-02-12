"""상품 관리 — Tab 4: 수동 등록"""
import os
import logging
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import text

from app.dashboard_utils import (
    query_df, query_df_cached, run_sql, create_wing_client,
    engine, CoupangWingError,
)
from uploaders.coupang_api_uploader import CoupangAPIUploader, _build_book_notices, _build_book_attributes
from app.constants import (
    WING_ACCOUNT_ENV_MAP, BOOK_CATEGORY_MAP, BOOK_DISCOUNT_RATE,
    COUPANG_FEE_RATE, DEFAULT_SHIPPING_COST, DEFAULT_STOCK,
    determine_delivery_charge_type,
    match_publisher_from_text,
)
from config.publishers import get_publisher_info

logger = logging.getLogger(__name__)


def render_tab_manual(account_id, selected_account, accounts_df, _wing_client):
    """Tab 4: 수동 등록 렌더링"""
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
                "SELECT b.title, b.author, pub.name as publisher_name, b.list_price FROM books b LEFT JOIN publishers pub ON b.publisher_id = pub.id WHERE b.isbn = :isbn LIMIT 1",
                {"isbn": _isbn_input}
            )
            if not _db_book.empty:
                _row = _db_book.iloc[0]
                st.session_state["m_title"] = _row["title"] or ""
                st.session_state["m_author"] = _row.get("author", "") or ""
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

