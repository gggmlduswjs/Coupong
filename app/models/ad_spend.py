"""광고비 정산 모델 (Excel 업로드 기반)"""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Date, DateTime, UniqueConstraint, Index
from datetime import datetime
from app.database import Base


class AdSpend(Base):
    """일별 캠페인별 광고비 정산 데이터"""

    __tablename__ = "ad_spends"
    __table_args__ = (
        UniqueConstraint("account_id", "ad_date", "campaign_id", name="uix_account_date_campaign"),
        Index("ix_ad_account_date", "account_id", "ad_date"),
        Index("ix_ad_date", "ad_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    ad_date = Column(Date, nullable=False)

    # 캠페인 정보
    campaign_id = Column(String(50), nullable=False)
    campaign_name = Column(String(200))
    ad_type = Column(String(20))       # PA 등
    ad_objective = Column(String(50))  # 매출 성장 등

    # 금액 정보
    daily_budget = Column(Integer, default=0)       # 광고 예산
    spent_amount = Column(Integer, default=0)       # 소진 광고비
    adjustment = Column(Integer, default=0)         # 소진 광고비 중 조정 금액
    spent_after_adjust = Column(Integer, default=0) # 조정 후 소진 광고비
    over_spend = Column(Integer, default=0)         # 초과 소진 금액
    billable_cost = Column(Integer, default=0)      # 청구 가능 광고비 (실제 비용)
    vat_amount = Column(Integer, default=0)         # 부가가치세
    total_charge = Column(Integer, default=0)       # 청구금액(+부가가치세)

    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AdSpend(date={self.ad_date}, campaign={self.campaign_id}, cost={self.billable_cost})>"
