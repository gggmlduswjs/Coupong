"""데이터베이스 연결 및 세션 관리"""
import time
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

_logger = logging.getLogger(__name__)

# SQLAlchemy 엔진 생성
_connect_args = {}
if "sqlite" in settings.database_url:
    _connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    echo=False,
    pool_pre_ping=True,
)

# SQLite WAL 모드 + busy_timeout (동시 읽기/쓰기 허용)
if "sqlite" in settings.database_url:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        # busy_timeout은 항상 설정 (잠금 시 대기)
        cursor.execute("PRAGMA busy_timeout=30000")
        # WAL 모드 전환 시도 (잠금 상태면 무시)
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except Exception:
            _logger.debug("WAL 모드 전환 실패 (DB 잠금), 기존 journal 모드 유지")
        cursor.close()

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
