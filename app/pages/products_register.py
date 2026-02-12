"""상품 관리 — Tab 3: 신규 등록"""
import logging
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder
from sqlalchemy import text

from app.dashboard_utils import (
    query_df, query_df_cached, run_sql, create_wing_client,
    product_to_upload_data, engine, CoupangWingError,
)
from uploaders.coupang_api_uploader import CoupangAPIUploader
from app.constants import (
    BOOK_DISCOUNT_RATE, COUPANG_FEE_RATE, DEFAULT_SHIPPING_COST,
    DEFAULT_STOCK,
    determine_customer_shipping_fee,
    determine_delivery_charge_type,
)

logger = logging.getLogger(__name__)


def render_tab_register(account_id, selected_account, accounts_df, _wing_client):
    """Tab 3: 신규 등록 렌더링"""
    try:
      # WING API 활성 계정 로드 (멀티 계정 등록용)
      _wing_accounts = accounts_df[accounts_df["wing_api_enabled"] == 1].to_dict("records")
      _wing_account_cnt = len(_wing_accounts)

      # 전체 ready 상품 + 계정별 등록 현황
      ready = query_df("""
          SELECT p.id as product_id, b.title, pub.name as publisher_name,
                 b.isbn, b.list_price, p.sale_price, p.net_margin,
                 p.shipping_policy, p.supply_rate, b.year,
                 COALESCE(b.sales_point, 0) as sales_point,
                 COALESCE(lc.listed_count, 0) as listed_count,
                 COALESCE(lc.listed_accounts, '') as listed_accounts
          FROM products p
          JOIN books b ON p.book_id = b.id
          LEFT JOIN publishers pub ON b.publisher_id = pub.id
          LEFT JOIN (
              SELECT COALESCE(l.isbn, l.product_name) as match_key,
                     COUNT(DISTINCT l.account_id) as listed_count,
                     STRING_AGG(DISTINCT a.account_name, ',') as listed_accounts
              FROM listings l
              JOIN accounts a ON l.account_id = a.id
              GROUP BY COALESCE(l.isbn, l.product_name)
          ) lc ON lc.match_key = COALESCE(b.isbn, b.title)
          WHERE p.status = 'ready' AND p.can_upload_single = true
          ORDER BY COALESCE(b.sales_point, 0) DESC, p.net_margin DESC
      """)

      # ── 마진/배송비 실시간 재계산 ──
      def _recalc_margin(row):
          """공급률+정가 기준 마진/배송정책 재계산
          - free: 셀러가 배송비 전액 부담 → 순마진 = 마진 - 2,300
          - paid: 고객 부담분만큼 셀러 비용 감소 → 순마진 = 마진 - (2,300 - 고객부담)
          """
          lp = int(row.get("list_price", 0) or 0)
          sr = float(row.get("supply_rate", 0.65) or 0.65)
          margin_rate_pct = int(round(sr * 100))
          sp = int(lp * BOOK_DISCOUNT_RATE)
          supply_cost = int(lp * sr)
          fee = int(sp * COUPANG_FEE_RATE)
          margin = sp - supply_cost - fee
          # 공급률+정가 기반 배송비 결정
          customer_fee = determine_customer_shipping_fee(margin_rate_pct, lp)
          seller_ship = DEFAULT_SHIPPING_COST - customer_fee
          actual_net = margin - seller_ship
          policy = "free" if customer_fee == 0 else "paid"
          return pd.Series({
              "calc_sale": sp, "calc_supply": supply_cost, "calc_fee": fee,
              "calc_margin": margin, "calc_net": actual_net, "calc_ship": policy,
              "calc_customer_fee": customer_fee,
          })

      if not ready.empty:
          _calc = ready.apply(_recalc_margin, axis=1)
          ready = pd.concat([ready, _calc], axis=1)
          ready["ship_changed"] = ready["shipping_policy"] != ready["calc_ship"]

      _all_listed_cnt = len(ready[ready["listed_count"] >= _wing_account_cnt]) if not ready.empty else 0
      _ready_cnt = len(ready) if not ready.empty else 0
      _unlisted_cnt = _ready_cnt - _all_listed_cnt

      k1, k2, k3 = st.columns(3)
      k1.metric("등록 가능", f"{_ready_cnt}건")
      k2.metric("미등록 계정 있음", f"{_unlisted_cnt}건")
      k3.metric(f"전 계정 등록 완료", f"{_all_listed_cnt}건")

      # DB 배송정책 불일치 일괄 반영
      ship_changed_cnt = int(ready["ship_changed"].sum()) if not ready.empty and "ship_changed" in ready.columns else 0
      if not ready.empty and ship_changed_cnt > 0:
          if st.button(f"DB 배송정책 동기화 ({ship_changed_cnt}건)", key="btn_recalc_apply"):
              _update_cnt = 0
              for _, _r in ready[ready["ship_changed"]].iterrows():
                  try:
                      run_sql(
                          "UPDATE products SET sale_price=:sp, net_margin=:nm, shipping_policy=:sh WHERE id=:id",
                          {"sp": int(_r["calc_sale"]), "nm": int(_r["calc_net"]),
                           "sh": _r["calc_ship"], "id": int(_r["product_id"])}
                      )
                      _update_cnt += 1
                  except Exception as _e:
                      logger.warning(f"재계산 적용 실패 (pid={_r['product_id']}): {_e}")
              st.success(f"DB 동기화 완료: {_update_cnt}건")
              st.cache_data.clear()
              st.rerun()

      # 알라딘 크롤링
      with st.expander("알라딘에서 새 도서 검색"):
          cr_col1, cr_col2 = st.columns([3, 1])
          with cr_col1:
              crawl_max = st.number_input("출판사당 최대 검색 수", value=20, step=10, min_value=5, max_value=50, key="cr_max")
          with cr_col2:
              btn_crawl = st.button("크롤링 시작", type="primary", key="btn_crawl", width="stretch")
          if btn_crawl:
              from scripts.franchise_sync import FranchiseSync
              sync = FranchiseSync()
              try:
                  crawl_progress = st.progress(0, text="출판사별 알라딘 검색 중...")
                  crawl_result = sync.crawl_by_publisher(
                      max_per_publisher=crawl_max,
                      progress_callback=lambda cur, tot, msg: crawl_progress.progress(cur / tot if tot > 0 else 0, text=msg),
                  )
                  crawl_progress.progress(0.9, text="마진 분석 중...")
                  analyze_result = sync.analyze_products(crawl_result["books"])
                  crawl_progress.progress(1.0, text="완료!")
                  st.success(f"검색 {crawl_result['searched']}개 → 신규 {crawl_result['new']}개, Product {analyze_result['created']}개")
                  query_df.clear()
                  st.rerun()
              except Exception as e:
                  st.error(f"크롤링 오류: {e}")
              finally:
                  sync.close()

      st.divider()

      if ready.empty:
          st.info("등록 가능한 신규 상품이 없습니다. 알라딘 크롤링을 해보세요.")

      # 필터 (출판사 + 최소 마진 + 등록 완료 제외)
      cf1, cf2, cf3 = st.columns([1, 1, 1])
      with cf1:
          pubs = ["전체"] + sorted(ready["publisher_name"].dropna().unique().tolist())
          pub_f = st.selectbox("출판사", pubs, key="nr_pub")
      with cf2:
          min_m = st.number_input("최소 마진(원)", value=0, step=500, key="nr_mm")
      with cf3:
          hide_full = st.checkbox("전 계정 등록 완료 숨김", value=True, key="nr_hide_full")

      filtered = ready.copy()
      if hide_full:
          filtered = filtered[filtered["listed_count"] < _wing_account_cnt]
      if pub_f != "전체":
          filtered = filtered[filtered["publisher_name"] == pub_f]
      if min_m > 0:
          _margin_col = "calc_net" if "calc_net" in filtered.columns else "net_margin"
          filtered = filtered[filtered[_margin_col] >= min_m]

      if filtered.empty:
          st.info("필터 조건에 맞는 상품이 없습니다.")

      # ── 일괄 승인/거부 버튼 (그리드 위) ──
      ba1, ba2, ba3 = st.columns([2, 1, 1])
      with ba1:
          st.markdown(f"**조회: {len(filtered)}건**")

      # ── 상품 테이블 (AgGrid) ──
      display = filtered.copy()

      def _ship_display(row):
          """배송비 표시: 무료 / 조건부(X원/Y만↑무료)"""
          cf = int(row.get("calc_customer_fee", 0)) if "calc_customer_fee" in row.index else 0
          policy = row.get("calc_ship", row.get("shipping_policy", "paid"))
          if policy == "free":
              return "무료배송"
          sr_pct = int(round(float(row.get("supply_rate", 0.65) or 0.65) * 100))
          if sr_pct > 70:
              thr = "6만"
          elif sr_pct > 67:
              thr = "3만"
          elif sr_pct > 65:
              thr = "2.5만"
          else:
              thr = "2만"
          fee = cf if cf > 0 else 2300
          return f"조건부({fee:,}원/{thr}↑무료)"
      display["배송"] = display.apply(_ship_display, axis=1)
      display["공급율"] = (display["supply_rate"] * 100).round(0).astype(int).astype(str) + "%" if "supply_rate" in display.columns else ""
      display["순마진"] = display["calc_net"].astype(int) if "calc_net" in display.columns else display["net_margin"].astype(int)
      # 등록 현황: "0/5" 또는 "2/5 (007-book,007-ez)"
      def _fmt_listed(row):
          cnt = int(row["listed_count"])
          accs = str(row.get("listed_accounts", "") or "")
          if cnt == 0 or not accs:
              return f"0/{_wing_account_cnt}"
          return f"{cnt}/{_wing_account_cnt} ({accs})"
      display["등록"] = display.apply(_fmt_listed, axis=1)

      display["판매지수"] = display["sales_point"].astype(int) if "sales_point" in display.columns else 0
      nr_grid_df = display[["title", "publisher_name", "list_price", "sale_price", "순마진", "판매지수", "공급율", "배송", "등록", "isbn", "year"]].rename(columns={
          "title": "제목", "publisher_name": "출판사", "isbn": "ISBN",
          "list_price": "정가", "sale_price": "판매가", "year": "연도",
      })
      nr_gb = GridOptionsBuilder.from_dataframe(nr_grid_df)
      nr_gb.configure_selection(selection_mode="multiple", use_checkbox=True)
      nr_gb.configure_column("제목", headerCheckboxSelection=True, minWidth=250)
      nr_gb.configure_column("판매지수", width=80, sort="desc")
      nr_gb.configure_column("공급율", width=70)
      nr_gb.configure_column("배송", width=100)
      nr_gb.configure_column("등록", minWidth=150)
      nr_gb.configure_grid_options(domLayout="normal", suppressRowClickSelection=True)
      _nr_grid_ver = st.session_state.get("nr_grid_ver", 0)
      nr_grid = AgGrid(
          nr_grid_df,
          gridOptions=nr_gb.build(),
          update_on=["selectionChanged", "cellClicked"],
          height=400,
          theme="streamlit",
          key=f"nr_aggrid_{_nr_grid_ver}",
      )

      # ── 체크박스 선택 → 등록용 (session_state 보존) ──
      nr_selected = nr_grid["selected_rows"]
      if nr_selected is not None:
          _sel_df = nr_selected if isinstance(nr_selected, pd.DataFrame) else pd.DataFrame(nr_selected)
          if len(_sel_df) > 0:
              st.session_state["nr_sel_titles"] = _sel_df["제목"].tolist()
          else:
              st.session_state["nr_sel_titles"] = []
      _persisted_titles = st.session_state.get("nr_sel_titles", [])
      sel_idx = [i for i, t in enumerate(display["title"]) if t in _persisted_titles]
      sel_cnt = len(sel_idx)

      # ── 행 클릭 → 상세보기용 (체크박스와 독립) ──
      _event = nr_grid.get("event_data")
      if _event and isinstance(_event, dict):
          _row_data = _event.get("data") or _event.get("rowData")
          if _row_data and isinstance(_row_data, dict) and _row_data.get("제목"):
              st.session_state["nr_detail_title"] = _row_data["제목"]

      st.markdown(f"**선택: {sel_cnt}건**")
      ap1, ap2 = st.columns([1, 5])
      with ap1:
          if st.button("선택 초기화", disabled=(sel_cnt == 0), key="btn_nr_clear"):
              st.session_state["nr_sel_titles"] = []
              st.session_state["nr_grid_ver"] = _nr_grid_ver + 1
              st.rerun()

      # ── 행 클릭 → 상세 보기 ──
      _detail_title = st.session_state.get("nr_detail_title")
      if _detail_title:
          _match = display[display["title"] == _detail_title]
          if not _match.empty:
              nr_sel = _match.iloc[0]
              book_id_row = query_df("SELECT id FROM books WHERE isbn = :isbn LIMIT 1", {"isbn": nr_sel["isbn"]}) if nr_sel["isbn"] else pd.DataFrame()

              st.divider()
              pv1, pv2 = st.columns([1, 3])
              with pv1:
                  st.markdown('<div style="width:150px;height:200px;background:#f0f0f0;display:flex;align-items:center;justify-content:center;border-radius:8px;color:#999;font-size:40px;">📖</div>', unsafe_allow_html=True)
              with pv2:
                  st.markdown(f"**{nr_sel['title']}**")
                  st.markdown(f"{nr_sel['publisher_name']} | ISBN: `{nr_sel['isbn']}`")
                  _detail_net = int(nr_sel.get('calc_net', nr_sel.get('net_margin', 0)) or 0)
                  st.markdown(f"정가 {int(nr_sel['list_price']):,}원 → 판매가 {int(nr_sel['sale_price']):,}원 | 순마진 **{_detail_net:,}원**")
                  # 등록된 계정 표시
                  _listed_accs = str(nr_sel.get("listed_accounts", "") or "")
                  _listed_cnt = int(nr_sel.get("listed_count", 0))
                  if _listed_cnt > 0 and _listed_accs:
                      st.markdown(f"등록 계정: **{_listed_accs}** ({_listed_cnt}/{_wing_account_cnt})")
                  else:
                      st.markdown(f"등록 계정: 없음 (0/{_wing_account_cnt})")

              with st.expander("수정 / 삭제"):
                  bid = int(book_id_row.iloc[0]["id"]) if not book_id_row.empty else None
                  pid = int(nr_sel["product_id"])
                  if bid:
                      with st.form("nr_edit_form"):
                          # 1행: 제목
                          ed_title = st.text_input("제목", value=nr_sel["title"] or "")
                          # 2행: 판매가 / 정가 / 배송
                          ed1, ed2, ed3 = st.columns(3)
                          with ed1:
                              ed_sale = st.number_input("판매가", value=int(nr_sel["sale_price"]), step=100)
                          with ed2:
                              ed_price = st.number_input("정가", value=int(nr_sel["list_price"]), step=100)
                          with ed3:
                              ed_ship = st.selectbox("배송", ["free", "paid"],
                                                     index=0 if nr_sel["shipping_policy"] == "free" else 1)

                          if st.form_submit_button("저장", type="primary"):
                              try:
                                  # books 테이블 업데이트
                                  run_sql(
                                      "UPDATE books SET title=:t, list_price=:lp WHERE id=:id",
                                      {"t": ed_title, "lp": ed_price, "id": bid}
                                  )
                                  # products 테이블 업데이트 (마진 재계산)
                                  _sr = float(nr_sel.get("supply_rate", 0.65) or 0.65)
                                  _supply_cost = int(ed_price * _sr)
                                  _fee = int(ed_sale * COUPANG_FEE_RATE)
                                  nm = ed_sale - _supply_cost - _fee - DEFAULT_SHIPPING_COST
                                  run_sql("UPDATE products SET sale_price=:sp, net_margin=:nm, shipping_policy=:sh WHERE id=:id",
                                          {"sp": ed_sale, "nm": int(nm), "sh": ed_ship, "id": pid})
                                  st.success("저장 완료")
                                  st.cache_data.clear()
                                  st.rerun()
                              except Exception as e:
                                  st.error(f"저장 실패: {e}")

                      del_confirm = st.text_input("삭제하려면 '삭제' 입력", key="nr_del_confirm")
                      if st.button("삭제", type="primary", disabled=(del_confirm != "삭제"), key="nr_del_btn"):
                          try:
                              run_sql("DELETE FROM products WHERE id=:id", {"id": pid})
                              if not book_id_row.empty:
                                  run_sql("DELETE FROM books WHERE id=:id", {"id": int(book_id_row.iloc[0]["id"])})
                              st.success("삭제 완료")
                              st.session_state.pop("nr_detail_title", None)
                              st.cache_data.clear()
                              st.rerun()
                          except Exception as e:
                              st.error(f"삭제 실패: {e}")

      st.divider()

      # ── 등록 매트릭스 프리뷰 + 일괄 등록 ──
      # 모든 선택된 상품은 등록 가능 (registration_status 삭제됨)
      _approved_sel_idx = sel_idx
      _approved_cnt = len(_approved_sel_idx)
      _unapproved_cnt = 0

      st.subheader("일괄 등록")

      if not _wing_accounts:
          st.warning("WING API가 활성화된 계정이 없습니다.")
      else:
          # 상품 × 계정 매트릭스 (등록됨=✓ 텍스트, 미등록=체크박스)
          _selected_pairs = {}  # {mi: [acc_objs]}
          _total_missing = 0
          _registered_map = {}

          if _approved_cnt > 0:
              _acc_cnt = len(_wing_accounts)
              # 헤더
              _hdr = st.columns([3] + [1] * _acc_cnt)
              _hdr[0].markdown("**상품명**")
              for _ai, _acc in enumerate(_wing_accounts):
                  _hdr[_ai + 1].markdown(f"**{_acc['account_name']}**")

              for _mi, idx in enumerate(_approved_sel_idx):
                  row = display.iloc[idx]
                  _name = str(row.get("title", ""))[:30]
                  _listed_str = str(row.get("listed_accounts", "") or "")
                  _listed = set(a.strip() for a in _listed_str.split(",") if a.strip())

                  _cols = st.columns([3] + [1] * _acc_cnt)
                  _cols[0].write(_name)

                  _sel_accs = []
                  _reg_row = {}
                  for _ai, _acc in enumerate(_wing_accounts):
                      _aname = _acc["account_name"]
                      _is_reg = _aname in _listed
                      _reg_row[_aname] = _is_reg
                      if _is_reg:
                          _cols[_ai + 1].markdown("✅")
                      else:
                          _chk = _cols[_ai + 1].checkbox(
                              _aname, value=True,
                              key=f"nr_reg_{_mi}_{_aname}",
                              label_visibility="collapsed",
                          )
                          if _chk:
                              _sel_accs.append(_acc)
                              _total_missing += 1
                  _selected_pairs[_mi] = _sel_accs
                  _registered_map[_mi] = _reg_row

              st.caption("✅ = 이미 등록됨 · ☑ = 신규 등록 예정 · 체크 해제 = 등록 제외")

          # 요약 + 버튼
          _summary_parts = [f"등록 예정 **{_total_missing}건**"]
          if _unapproved_cnt > 0:
              _summary_parts.append(f"미승인 {_unapproved_cnt}건 제외")
          cb1, cb2, cb3 = st.columns([3, 1, 3])
          with cb1:
              st.markdown(" | ".join(_summary_parts))
          with cb2:
              dry = st.checkbox("Dry Run", value=False, key="dry", help="체크 시 실제 등록 안 하고 확인만")
          with cb3:
              btn = st.button(
                  f"{'테스트' if dry else '선택 항목 등록'} ({_total_missing}건)",
                  type="primary", disabled=(_total_missing == 0),
              )

          if btn and _approved_cnt > 0 and _total_missing > 0:
              progress = st.progress(0, text="준비 중...")
              result_box = st.container()
              ok_list, fail_list = [], []
              _done = 0

              for _mi, idx in enumerate(_approved_sel_idx):
                  row = display.iloc[idx]
                  pd_data = product_to_upload_data(row)
                  name = pd_data["product_name"]
                  _row_listed = set(a.strip() for a in str(row.get("listed_accounts", "") or "").split(",") if a.strip())

                  for _acc in _selected_pairs.get(_mi, []):
                      _acc_name = _acc["account_name"]

                      _done += 1
                      progress.progress(min(_done / _total_missing, 1.0), text=f"[{_done}/{_total_missing}] {_acc_name} — {name[:25]}...")

                      _out_code = str(_acc.get("outbound_shipping_code", ""))
                      _ret_code = str(_acc.get("return_center_code", ""))

                      if not _out_code or not _ret_code:
                          fail_list.append({"계정": _acc_name, "제목": name[:35], "결과": "출고지/반품지 미설정"})
                          continue

                      _client = create_wing_client(_acc)
                      if _client is None:
                          fail_list.append({"계정": _acc_name, "제목": name[:35], "결과": "API 키 미설정"})
                          continue

                      _uploader = CoupangAPIUploader(_client, vendor_user_id=_acc_name)

                      if dry:
                          try:
                              _uploader.build_product_payload(pd_data, _out_code, _ret_code)
                              ok_list.append({"계정": _acc_name, "제목": name[:35], "ISBN": pd_data["isbn"], "결과": "OK"})
                          except Exception as e:
                              fail_list.append({"계정": _acc_name, "제목": name[:35], "결과": str(e)[:80]})
                      else:
                          res = _uploader.upload_product(pd_data, _out_code, _ret_code, dashboard_override=True)
                          if res["success"]:
                              sid = res["seller_product_id"]
                              ok_list.append({"계정": _acc_name, "제목": name[:35], "쿠팡ID": sid, "결과": "성공"})
                              # 배송비 계산
                              _mr = int(pd_data.get("margin_rate", 65))
                              _lp = int(pd_data.get("original_price", 0))
                              _dct, _dc, _fsoa = determine_delivery_charge_type(_mr, _lp)
                              try:
                                  with engine.connect() as conn:
                                      conn.execute(text("""
                                          INSERT INTO listings
                                          (account_id, product_id, isbn, coupang_product_id,
                                           coupang_status, sale_price, original_price, product_name,
                                           stock_quantity, delivery_charge_type, delivery_charge, free_ship_over_amount,
                                           synced_at)
                                          VALUES (:aid, :pid, :isbn, :cid, 'active', :sp, :op, :pn,
                                                  :stock, :dct, :dc, :fsoa, :now)
                                          ON CONFLICT DO NOTHING
                                      """), {
                                          "aid": int(_acc["id"]), "pid": int(row["product_id"]),
                                          "isbn": pd_data["isbn"], "cid": sid,
                                          "sp": pd_data["sale_price"], "op": pd_data["original_price"],
                                          "pn": name,
                                          "stock": DEFAULT_STOCK, "dct": _dct, "dc": _dc, "fsoa": _fsoa,
                                          "now": datetime.now().isoformat(),
                                      })
                                      # 이번 등록 반영 → 전 계정 완료 여부 체크
                                      _row_listed.add(_acc_name)
                                      if len(_row_listed) >= _wing_account_cnt:
                                          conn.execute(text(
                                              "UPDATE products SET status = 'uploaded' WHERE id = :id"
                                          ), {"id": int(row["product_id"])})
                                      conn.commit()
                              except Exception as db_e:
                                  logger.warning(f"DB 저장 실패 ({_acc_name}): {db_e}")
                          else:
                              fail_list.append({"계정": _acc_name, "제목": name[:35], "결과": res["message"][:80]})

              progress.progress(1.0, text="완료!")
              with result_box:
                  if ok_list:
                      st.success(f"성공: {len(ok_list)}건")
                      st.dataframe(pd.DataFrame(ok_list), width="stretch", hide_index=True)
                  if fail_list:
                      st.error(f"실패: {len(fail_list)}건")
                      st.dataframe(pd.DataFrame(fail_list), width="stretch", hide_index=True)
              query_df.clear()
              st.session_state.pop("nr_sel_titles", None)
              if ok_list and not dry:
                  import time
                  time.sleep(1)
                  st.cache_data.clear()
                  st.rerun()


    except Exception:
      pass  # Tab 3 에러가 Tab 4를 죽이지 않도록
