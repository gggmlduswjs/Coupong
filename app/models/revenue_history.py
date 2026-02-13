"""매출 내역 모델 (WING Revenue History API 원본 데이터)"""
from sqlalchemy import Column, Integer, BigInteger, String, Float, ForeignKey, Date, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class RevenueHistory(Base):
    """주문-아이템 단위 매출 내역 (Revenue History API 원본)"""

    __tablename__ = "revenue_history"
    __table_args__ = (
        UniqueConstraint("account_id", "order_id", "vendor_item_id", name="uix_account_order_item"),
        Index("ix_rev_account_date", "account_id", "recognition_date"),
        Index("ix_rev_recognition", "recognition_date"),
        Index("ix_rev_listing", "listing_id"),
        Index("ix_rev_sale_type", "sale_type"),
        Index("ix_rev_sale_date", "sale_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)

    # 주문 정보
    order_id = Column(BigInteger, nullable=False)
    sale_type = Column(String(50), nullable=False)  # SALE / REFUND
    sale_date = Column(Date, nullable=False)
    recognition_date = Column(Date, nullable=False)
    settlement_date = Column(Date)

    # 상품 정보
    product_id = Column(BigInteger)  # 쿠팡 노출상품 ID
    product_name = Column(String(500))
    vendor_item_id = Column(BigInteger)
    vendor_item_name = Column(String(500))

    # 금액 정보
    sale_price = Column(Integer, default=0)          # 총 판매가 (수량 반영)
    quantity = Column(Integer, default=0)
    coupang_discount = Column(Integer, default=0)    # 쿠팡지원할인
    sale_amount = Column(Integer, default=0)         # 매출금액
    seller_discount = Column(Integer, default=0)     # 판매자할인쿠폰
    service_fee = Column(Integer, default=0)         # 서비스이용료
    service_fee_vat = Column(Integer, default=0)
    service_fee_ratio = Column(Float)                # 서비스이용율(%)
    settlement_amount = Column(Integer, default=0)   # 정산금액
    delivery_fee_amount = Column(Integer, default=0)
    delivery_fee_settlement = Column(Integer, default=0)

    # 매칭
    listing_id = Column(Integer, ForeignKey("listings.id"))

    # Relationships
    account = relationship("Account", backref="revenue_history")
    listing = relationship("Listing", back_populates="revenue_history")

    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<RevenueHistory(order={self.order_id}, item={self.vendor_item_id}, type={self.sale_type})>"
