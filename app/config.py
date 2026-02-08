"""애플리케이션 설정"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """환경변수 기반 설정"""

    # Database
    database_url: str = "sqlite:///./coupang_auto.db"

    # Supabase PostgreSQL — Streamlit Cloud 배포용
    supabase_database_url: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_service_key: Optional[str] = None
    supabase_anon_key: Optional[str] = None

    # Turso (libSQL) — 레거시
    turso_database_url: Optional[str] = None
    turso_auth_token: Optional[str] = None

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Security
    encryption_key: str

    # Crawler
    crawl_delay_min: float = 1.0
    crawl_delay_max: float = 3.0
    crawl_max_items_per_session: int = 100
    crawl_timeout: int = 30

    # Upload
    upload_delay_min: float = 5.0
    upload_delay_max: float = 10.0
    upload_max_daily_per_account: int = 20
    upload_enable_playwright: bool = False

    # Analysis
    analysis_period_days: int = 7
    analysis_exposure_low_threshold: int = 10
    analysis_conversion_low_threshold: int = 50

    # Notification
    enable_kakao_notification: bool = False
    kakao_api_key: Optional[str] = None

    enable_email_notification: bool = False
    email_smtp_server: Optional[str] = None
    email_smtp_port: Optional[int] = None
    email_smtp_user: Optional[str] = None
    email_smtp_password: Optional[str] = None
    email_from: Optional[str] = None
    email_to: Optional[str] = None

    # Logging
    log_level: str = "INFO"
    log_file_max_bytes: int = 10485760  # 10MB
    log_backup_count: int = 5

    # Aladin API
    aladin_ttb_key: Optional[str] = None

    # Coupang Accounts (5개)
    coupang_id_1: Optional[str] = None
    coupang_pw_1: Optional[str] = None
    coupang_id_2: Optional[str] = None
    coupang_pw_2: Optional[str] = None
    coupang_id_3: Optional[str] = None
    coupang_pw_3: Optional[str] = None
    coupang_id_4: Optional[str] = None
    coupang_pw_4: Optional[str] = None
    coupang_id_5: Optional[str] = None
    coupang_pw_5: Optional[str] = None

    # Coupang WING API
    coupang_007book_vendor_id: Optional[str] = None
    coupang_007book_access_key: Optional[str] = None
    coupang_007book_secret_key: Optional[str] = None
    coupang_007bm_vendor_id: Optional[str] = None
    coupang_007bm_access_key: Optional[str] = None
    coupang_007bm_secret_key: Optional[str] = None
    coupang_007ez_vendor_id: Optional[str] = None
    coupang_007ez_access_key: Optional[str] = None
    coupang_007ez_secret_key: Optional[str] = None
    coupang_002bm_vendor_id: Optional[str] = None
    coupang_002bm_access_key: Optional[str] = None
    coupang_002bm_secret_key: Optional[str] = None
    coupang_big6ceo_vendor_id: Optional[str] = None
    coupang_big6ceo_access_key: Optional[str] = None
    coupang_big6ceo_secret_key: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = False


# 전역 설정 인스턴스
settings = Settings()
