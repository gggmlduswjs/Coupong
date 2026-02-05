"""정산 내역 모델 (WING Settlement History API 원본 데이터)"""
from sqlalchemy import Column, Integer, BigInteger, String, Float, ForeignKey, Date, DateTime, UniqueConstraint, Index
from datetime import datetime
from app.database import Base


class SettlementHistory(Base):
    """계정별 월간 정산 내역 (Settlement History API 원본)"""

    __tablename__ = "settlement_history"
    __table_args__ = (
        UniqueConstraint("account_id", "year_month", "settlement_type", "settlement_date",
                         name="uix_account_month_type_date"),
        Index("ix_settle_account_month", "account_id", "year_month"),
        Index("ix_settle_month", "year_month"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    year_month = Column(String(7), nullable=False)  # YYYY-MM

    # 정산 유형/상태
    settlement_type = Column(String(20))     # MONTHLY/WEEKLY/ADDITIONAL/RESERVE
    settlement_date = Column(String(10))     # 정산(예정)일
    settlement_status = Column(String(20))   # DONE/SUBJECT

    # 매출인식 기간
    revenue_date_from = Column(String(10))
    revenue_date_to = Column(String(10))

    # 금액 정보
    total_sale = Column(Integer, default=0)                  # 총판매액
    service_fee = Column(Integer, default=0)                 # 판매수수료
    settlement_target_amount = Column(Integer, default=0)    # 정산대상액
    settlement_amount = Column(Integer, default=0)           # 지급액
    last_amount = Column(Integer, default=0)                 # 유보금
    pending_released_amount = Column(Integer, default=0)     # 보류해제금
    seller_discount_coupon = Column(Integer, default=0)      # 판매자할인쿠폰
    downloadable_coupon = Column(Integer, default=0)         # 다운로드쿠폰
    seller_service_fee = Column(Integer, default=0)          # 판매자서비스수수료
    courantee_fee = Column(Integer, default=0)               # 보증수수료
    deduction_amount = Column(Integer, default=0)            # 차감금액
    debt_of_last_week = Column(Integer, default=0)           # 전주차이월금
    final_amount = Column(Integer, default=0)                # 최종지급액

    # 계좌 정보
    bank_name = Column(String(50))
    bank_account = Column(String(50))

    # 원본 JSON
    raw_json = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SettlementHistory(month={self.year_month}, type={self.settlement_type}, status={self.settlement_status})>"
