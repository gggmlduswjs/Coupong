"""데이터베이스 연결 및 세션 관리 (PostgreSQL 전용)"""
import os
import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

_logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


# ─── URL 결정 ───

def _resolve_database_url() -> str:
    """DATABASE_URL 결정: 환경변수 → Streamlit secrets → app/config.py"""

    # 1) 환경변수
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    # 2) Streamlit secrets (Streamlit Cloud 배포 시)
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            # [supabase] 섹션
            if "supabase" in st.secrets:
                url = st.secrets["supabase"]["database_url"]
                if url:
                    return url
            # 최상위 키
            if "DATABASE_URL" in st.secrets:
                url = st.secrets["DATABASE_URL"]
                if url:
                    return url
    except Exception as e:
        _logger.warning(f"Streamlit secrets 읽기 실패: {e}")
        pass

    # 3) app/config.py 설정
    try:
        from app.config import settings
        if settings.supabase_database_url:
            return settings.supabase_database_url
    except Exception:
        pass

    raise RuntimeError(
        "DATABASE_URL이 설정되지 않았습니다. "
        "환경변수 DATABASE_URL 또는 .env의 SUPABASE_DATABASE_URL을 확인하세요."
    )


def _is_postgresql(url: str) -> bool:
    """PostgreSQL 여부 판별 (호환성 유지용, 항상 True)"""
    return url.startswith(("postgresql://", "postgres://"))


def _create_engine_for_url(url: str):
    """PostgreSQL 엔진 생성"""
    _logger.info("Supabase PostgreSQL 엔진으로 연결합니다.")
    return create_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,       # 30분마다 커넥션 재활용 (stale 방지)
        pool_timeout=10,         # 커넥션 대기 최대 10초
        connect_args={
            "connect_timeout": 5,           # DB 연결 타임아웃 5초
            "options": "-c statement_timeout=30000",  # 쿼리 타임아웃 30초
        },
    )


def get_engine_for_db(db_path: str = None):
    """스크립트용 엔진 헬퍼

    - db_path가 None이면 전역 URL 로직 사용
    - db_path가 PostgreSQL URL이면 해당 URL로 엔진 생성
    """
    if db_path is None:
        return _create_engine_for_url(_resolve_database_url())
    if db_path.startswith(("postgresql://", "postgres://")):
        return _create_engine_for_url(db_path)
    return _create_engine_for_url(db_path)


# ─── 모듈 레벨 전역 엔진 ───

_database_url = _resolve_database_url()
engine = _create_engine_for_url(_database_url)
_logger.info("DB 엔진 생성: Supabase PostgreSQL")

# 세션 팩토리
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 베이스 클래스
Base = declarative_base()


def get_db():
    """데이터베이스 세션 의존성"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """데이터베이스 초기화 (테이블 생성)"""
    Base.metadata.create_all(bind=engine)
