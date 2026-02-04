"""업로드 관리 페이지 - 5개 계정 동시 관리"""
import streamlit as st
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import sys

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.uploader_service import UploaderService
from app.services.account_manager import AccountManager
from app.services.job_queue import JobQueue
from app.database import get_db

st.set_page_config(
    page_title="업로드 관리",
    page_icon="⬆️",
    layout="wide"
)

# 세션 상태 초기화
if 'uploader_service' not in st.session_state:
    st.session_state.uploader_service = UploaderService()
    st.session_state.account_manager = AccountManager()
    st.session_state.job_queue = JobQueue()

uploader_service = st.session_state.uploader_service
account_manager = st.session_state.account_manager
job_queue = st.session_state.job_queue

st.title("⬆️ 업로드 관리 - 5개 계정 동시 관리")

# 1. 계정 상태 모니터링
st.header("📊 계정 상태")

account_status = account_manager.get_account_status_summary()

col1, col2, col3, col4, col5 = st.columns(5)

accounts_info = account_status.get('accounts', {})
for i, (account_id, status_info) in enumerate(accounts_info.items()):
    with [col1, col2, col3, col4, col5][i]:
        status = status_info.get('status', 'idle')
        details = status_info.get('details', {})
        
        # 상태별 색상
        if status == 'completed':
            color = "🟢"
            delta_value = details.get('success_count', 0)
        elif status == 'running':
            color = "🟡"
            delta_value = f"{details.get('current_product', 0)}/{details.get('total_products', 0)}"
        elif status == 'failed':
            color = "🔴"
            delta_value = None
        else:
            color = "⚪"
            delta_value = None
        
        st.metric(
            label=account_id,
            value=f"{color} {status}",
            delta=delta_value
        )
        
        if status_info.get('last_update'):
            st.caption(f"최근: {status_info['last_update'][:16]}")

# 2. 업로드 대기열
st.header("📤 업로드 대기열")

pending_jobs = job_queue.get_pending_jobs()

if pending_jobs:
    for job in pending_jobs:
        with st.expander(f"작업 {job.job_id} - {job.status} (우선순위: {job.priority})"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**대상 계정:** {', '.join(job.account_ids)}")
                st.write(f"**상품 수:** {len(job.products)}개")
                st.write(f"**생성일시:** {job.created_at}")
            
            with col2:
                st.write(f"**드라이런:** {'✅ 예' if job.dry_run else '❌ 아니오'}")
                st.write(f"**실행 모드:** {job.execution_mode}")
                st.write(f"**최대 워커:** {job.max_workers}")
            
            if st.button(f"작업 실행", key=f"run_{job.job_id}"):
                with st.spinner("작업 실행 중..."):
                    try:
                        db = next(get_db())
                        result = asyncio.run(
                            uploader_service.execute_job(job.job_id, db=db)
                        )
                        st.success(f"작업 완료: {result['success_count']}개 계정 성공")
                        st.rerun()
                    except Exception as e:
                        st.error(f"작업 실패: {e}")
else:
    st.info("대기 중인 작업이 없습니다.")

# 3. 새 작업 생성
st.header("➕ 새 업로드 작업 생성")

uploaded_file = st.file_uploader(
    "상품 데이터 JSON 파일 업로드",
    type=['json'],
    help="상품 정보가 담긴 JSON 파일을 업로드하세요"
)

if uploaded_file:
    try:
        products = json.load(uploaded_file)
        st.success(f"✅ {len(products)}개 상품 로드 완료")
        
        # 상품 미리보기
        with st.expander("상품 미리보기"):
            if products:
                st.json(products[0] if len(products) == 1 else products[:3])
    except Exception as e:
        st.error(f"파일 로드 실패: {e}")
        products = []
else:
    products = []

if products:
    # 계정 선택
    enabled_accounts = account_manager.get_enabled_accounts()
    account_options = {acc_id: f"{acc_id} ({acc_config.get('name', '')})" 
                       for acc_id, acc_config in enabled_accounts}
    
    selected_accounts = st.multiselect(
        "대상 계정 선택",
        options=list(account_options.keys()),
        default=list(account_options.keys()) if len(account_options) <= 5 else [],
        format_func=lambda x: account_options[x]
    )
    
    # 실행 옵션
    col1, col2, col3 = st.columns(3)
    
    with col1:
        dry_run = st.checkbox("드라이런 모드 (실제 등록 안 함)", value=True)
    
    with col2:
        execution_mode = st.selectbox(
            "실행 모드",
            ['sequential', 'parallel'],
            index=0,
            help="sequential: 순차 실행 (안전), parallel: 병렬 실행 (위험)"
        )
    
    with col3:
        max_workers = st.number_input(
            "최대 워커 수 (병렬 모드)",
            min_value=1,
            max_value=5,
            value=2,
            disabled=(execution_mode == 'sequential')
        )
    
    priority = st.slider("우선순위", min_value=1, max_value=5, value=1)
    
    if st.button("작업 추가", type="primary"):
        if selected_accounts and products:
            try:
                job_id = asyncio.run(
                    uploader_service.create_upload_job(
                        account_ids=selected_accounts,
                        products=products,
                        priority=priority,
                        dry_run=dry_run,
                        execution_mode=execution_mode,
                        max_workers=max_workers
                    )
                )
                st.success(f"✅ 작업 {job_id} 추가 완료!")
                st.rerun()
            except Exception as e:
                st.error(f"작업 추가 실패: {e}")
        else:
            st.warning("계정과 상품을 선택해주세요.")

# 4. 작업 이력
st.header("📋 작업 이력")

status_filter = st.selectbox(
    "상태 필터",
    ['전체', 'pending', 'running', 'completed', 'failed'],
    index=0
)

all_jobs = job_queue.get_all_jobs(
    status=None if status_filter == '전체' else status_filter
)

if all_jobs:
    for job_data in all_jobs:
        job = UploadJob.from_dict(job_data)
        
        status_emoji = {
            'pending': '⏳',
            'running': '🔄',
            'completed': '✅',
            'failed': '❌'
        }.get(job.status, '❓')
        
        with st.expander(f"{status_emoji} {job.job_id} - {job.status}"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**계정:** {', '.join(job.account_ids)}")
                st.write(f"**상품 수:** {len(job.products)}개")
                st.write(f"**생성일시:** {job.created_at}")
            
            with col2:
                st.write(f"**드라이런:** {job.dry_run}")
                st.write(f"**실행 모드:** {job.execution_mode}")
                st.write(f"**우선순위:** {job.priority}")
            
            if job.result:
                st.json(job.result)
            
            if job.error_message:
                st.error(f"오류: {job.error_message}")
            
            if job.status in ['completed', 'failed']:
                if st.button(f"작업 삭제", key=f"delete_{job.job_id}"):
                    job_queue.delete_job(job.job_id)
                    st.rerun()
else:
    st.info("작업 이력이 없습니다.")

# 5. 실시간 새로고침
if st.button("🔄 상태 새로고침"):
    st.rerun()

# 자동 새로고침 옵션
auto_refresh = st.checkbox("자동 새로고침 (30초)", value=False)
if auto_refresh:
    import time
    time.sleep(30)
    st.rerun()
