"""출판사 모델"""
from sqlalchemy import Column, Integer, String, Boolean, Text, Float, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base
from app.constants import BOOK_DISCOUNT_RATE, COUPANG_FEE_RATE, DEFAULT_SHIPPING_COST, FREE_SHIPPING_THRESHOLD


class Publisher(Base):
    """출판사 정보"""
    __tablename__ = "publishers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    margin_rate = Column(Integer, nullable=False)  # 매입률 (40~73)
    min_free_shipping = Column(Integer, nullable=False)  # 무료배송 기준 (원)
    supply_rate = Column(Float, nullable=False)  # 공급률 (0.27~0.60)
    is_active = Column(Boolean, default=True, index=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    books = relationship("Book", back_populates="publisher")
    bundle_skus = relationship("BundleSKU", back_populates="publisher")

    def __repr__(self):
        return f"<Publisher(name='{self.name}', margin_rate={self.margin_rate}%)>"

    @property
    def margin_percentage(self):
        """매입률 → 마진율 변환"""
        return 100 - self.margin_rate

    def calculate_margin(self, list_price: int, shipping_cost: int = DEFAULT_SHIPPING_COST) -> dict:
        """
        마진 계산

        Args:
            list_price: 정가
            shipping_cost: 배송비 (기본 DEFAULT_SHIPPING_COST원)

        Returns:
            {
                'sale_price': 판매가,
                'supply_cost': 공급가,
                'coupang_fee': 쿠팡 수수료,
                'margin_per_unit': 권당 마진,
                'net_margin': 순마진 (배송비 제외)
            }
        """
        sale_price = int(list_price * BOOK_DISCOUNT_RATE)
        supply_cost = int(list_price * self.supply_rate)
        coupang_fee = int(sale_price * COUPANG_FEE_RATE)
        margin_per_unit = sale_price - supply_cost - coupang_fee
        net_margin = margin_per_unit - shipping_cost

        return {
            'sale_price': sale_price,
            'supply_cost': supply_cost,
            'coupang_fee': coupang_fee,
            'margin_per_unit': margin_per_unit,
            'net_margin': net_margin,
            'shipping_cost': shipping_cost
        }

    def determine_shipping_policy(self, list_price: int) -> str:
        """
        배송 정책 자동 판단

        Returns:
            'free' - 무료배송 가능
            'paid' - 유료배송 권장
            'bundle_required' - 묶음 필수
        """
        margin_info = self.calculate_margin(list_price)
        net_margin = margin_info['net_margin']

        if net_margin >= FREE_SHIPPING_THRESHOLD:
            return 'free'
        elif net_margin >= 0:
            return 'paid'
        else:
            return 'bundle_required'

    def can_upload_single(self, list_price: int) -> bool:
        """단권 업로드 가능 여부"""
        policy = self.determine_shipping_policy(list_price)
        return policy in ['free', 'paid']
