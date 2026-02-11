"""광고 성과 상세 모델 (광고센터 보고서 기반)"""
from sqlalchemy import Column, Integer, BigInteger, String, Float, ForeignKey, Date, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class AdPerformance(Base):
    """광고 성과 상세 데이터 (상품/키워드/캠페인 보고서)"""

    __tablename__ = "ad_performances"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "ad_date", "campaign_id", "ad_group_name",
            "coupang_product_id", "keyword", "report_type",
            name="uix_ad_perf_unique",
        ),
        Index("ix_adperf_account_date", "account_id", "ad_date"),
        Index("ix_adperf_listing", "listing_id"),
        Index("ix_adperf_product", "coupang_product_id"),
        Index("ix_adperf_account_date_listing", "account_id", "ad_date", "listing_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    ad_date = Column(Date, nullable=False)

    # 광고 구조
    campaign_id = Column(String(50), default="")
    campaign_name = Column(String(200), default="")
    ad_group_name = Column(String(200), default="")

    # 상품 (상품 보고서용)
    coupang_product_id = Column(BigInteger, nullable=True)  # 쿠팡 상품ID
    product_name = Column(String(500), default="")
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=True)

    # 키워드 (키워드 보고서용)
    keyword = Column(String(200), default="")
    match_type = Column(String(20), default="")  # 정확/확장

    # 성과 지표
    impressions = Column(Integer, default=0)   # 노출수
    clicks = Column(Integer, default=0)        # 클릭수
    ctr = Column(Float, default=0.0)           # 클릭률 (%)
    avg_cpc = Column(Integer, default=0)       # 평균 CPC (원)
    ad_spend = Column(Integer, default=0)      # 광고비 (원)

    # 전환
    direct_orders = Column(Integer, default=0)     # 직접전환 주문수
    direct_revenue = Column(Integer, default=0)    # 직접전환 매출
    indirect_orders = Column(Integer, default=0)   # 간접전환 주문수
    indirect_revenue = Column(Integer, default=0)  # 간접전환 매출
    total_orders = Column(Integer, default=0)      # 총 전환 주문수
    total_revenue = Column(Integer, default=0)     # 총 전환 매출
    roas = Column(Float, default=0.0)              # ROAS (%)

    # 판매수량
    total_quantity = Column(Integer, default=0)      # 총판매수량
    direct_quantity = Column(Integer, default=0)     # 직접판매수량
    indirect_quantity = Column(Integer, default=0)   # 간접판매수량

    # 광고 구분 (상품광고 보고서)
    bid_type = Column(String(30), default="")        # 입찰유형
    sales_method = Column(String(20), default="")    # 판매방식 (3P/Retail)
    ad_type = Column(String(50), default="")         # 광고유형 (매출최적화/수동성과형)
    option_id = Column(String(50), default="")       # 광고진행 옵션ID

    # 브랜드/디스플레이 광고 전용
    ad_name = Column(String(200), default="")        # 광고명
    placement = Column(String(100), default="")      # 노출지면명/노출영역
    creative_id = Column(String(50), default="")     # 소재ID
    category = Column(String(200), default="")       # 카테고리

    # 메타
    report_type = Column(String(20), default="campaign")  # product, keyword, brand, display, campaign

    # Relationships
    account = relationship("Account", backref="ad_performances")
    listing = relationship("Listing", back_populates="ad_performances")

    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return (
            f"<AdPerformance(date={self.ad_date}, type={self.report_type}, "
            f"spend={self.ad_spend}, roas={self.roas})>"
        )
