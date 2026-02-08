"""데이터베이스 연결 및 세션 관리

로컬 SQLite / Supabase PostgreSQL 자동 분기:
  - DATABASE_URL에 postgresql:// 이 있으면 Supabase 사용
  - Streamlit secrets에 supabase 설정이 있으면 Supabase 사용
  - 없으면 로컬 SQLite 사용
"""
import os
import logging
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

_logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


# ─── URL 결정 ───

def _resolve_database_url() -> str:
    """DATABASE_URL 결정: 환경변수 → Streamlit secrets → 로컬 SQLite 순"""

    # 1) 환경변수
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    # 2) Streamlit secrets (Streamlit Cloud 배포 시)
    try:
        import streamlit as st
        secrets = st.secrets

        # Supabase PostgreSQL
        supabase_url = secrets.get("supabase", {}).get("database_url")
        if supabase_url:
            return supabase_url

        # Turso (레거시 호환)
        turso_url = secrets.get("turso", {}).get("database_url")
        turso_token = secrets.get("turso", {}).get("auth_token")
        if turso_url and turso_token:
            sep = "&" if "?" in turso_url else "?"
            return f"{turso_url}{sep}authToken={turso_token}&secure=true"
    except Exception:
        pass

    # 3) app/config.py 설정
    try:
        from app.config import settings
        # Supabase
        if settings.supabase_database_url:
            return settings.supabase_database_url
        # Turso (레거시)
        if settings.turso_database_url and settings.turso_auth_token:
            url = settings.turso_database_url
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}authToken={settings.turso_auth_token}&secure=true"
    except Exception:
        pass

    # 4) 기본 로컬 SQLite
    db_path = ROOT / "coupang_auto.db"
    return f"sqlite:///{db_path}"


def _is_local_sqlite(url: str) -> bool:
    """로컬 SQLite 여부 판별"""
    return url.startswith("sqlite:///")


def _is_postgresql(url: str) -> bool:
    """PostgreSQL 여부 판별"""
    return url.startswith(("postgresql://", "postgres://"))


def _create_engine_for_url(url: str):
    """URL에 따라 적절한 엔진 생성"""
    if _is_local_sqlite(url):
        eng = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            echo=False,
            pool_pre_ping=True,
        )
        # SQLite WAL 모드 + busy_timeout
        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA busy_timeout=30000")
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except Exception:
                _logger.debug("WAL 모드 전환 실패 (DB 잠금), 기존 journal 모드 유지")
            cursor.close()
        return eng
    elif _is_postgresql(url):
        # Supabase PostgreSQL
        _logger.info("Supabase PostgreSQL 엔진으로 연결합니다.")
        return create_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    else:
        # Turso / libSQL (레거시)
        _logger.info("Turso(libSQL) 엔진으로 연결합니다.")
        return create_engine(
            url,
            echo=False,
            pool_pre_ping=True,
        )


def get_engine_for_db(db_path: str = None):
    """스크립트용 엔진 헬퍼

    - db_path가 None이면 전역 URL 로직 사용
    - db_path가 경로면 로컬 SQLite 엔진 생성
    - db_path가 URL이면 해당 URL로 엔진 생성
    """
    if db_path is None:
        return _create_engine_for_url(_resolve_database_url())
    # URL 형식인지 확인
    if db_path.startswith(("sqlite://", "libsql://", "https://", "postgresql://", "postgres://")):
        return _create_engine_for_url(db_path)
    # 파일 경로 → SQLite URL 변환
    return _create_engine_for_url(f"sqlite:///{db_path}")


# ─── 모듈 레벨 전역 엔진 ───

_database_url = _resolve_database_url()
engine = _create_engine_for_url(_database_url)

if _is_postgresql(_database_url):
    _db_type = "Supabase PostgreSQL"
elif _is_local_sqlite(_database_url):
    _db_type = "로컬 SQLite"
else:
    _db_type = "Turso(libSQL)"
_logger.info("DB 엔진 생성: %s", _db_type)

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
