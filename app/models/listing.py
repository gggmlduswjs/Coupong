"""상품 등록 현황 모델"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Listing(Base):
    """계정별 상품 등록 현황 (단권/묶음 모두 지원)"""

    __tablename__ = "listings"
    __table_args__ = (
        # 중복 방지: 동일 계정 + 동일 ISBN
        UniqueConstraint("account_id", "isbn", name="uix_account_isbn"),
        # 중복 방지: 동일 계정 + 동일 묶음키
        UniqueConstraint("account_id", "bundle_key", name="uix_account_bundle"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # 계정
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)

    # 상품 (단권 또는 묶음)
    product_type = Column(String(20), nullable=False, index=True)  # 'single', 'bundle'
    product_id = Column(Integer, ForeignKey("products.id"), index=True)  # 단권용
    bundle_id = Column(Integer, ForeignKey("bundle_skus.id"), index=True)  # 묶음용
    isbn = Column(String(13), index=True)  # 단권용
    bundle_key = Column(String(200), index=True)  # 묶음용

    # 쿠팡 정보
    coupang_product_id = Column(String(50))  # 쿠팡 상품 ID
    coupang_status = Column(String(20), default='pending', index=True)  # pending, active, sold_out

    # 상품 정보
    product_name = Column(String(500))  # 상품명 (쿠팡 표시명)
    original_price = Column(Integer, default=0)  # 정가

    # 판매 정보
    sale_price = Column(Integer, nullable=False)
    shipping_policy = Column(String(20), nullable=False)  # 'free', 'paid'

    # 업로드 정보
    upload_method = Column(String(20))  # csv, playwright
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    last_checked_at = Column(DateTime)
    error_message = Column(Text)

    # Relationships
    account = relationship("Account", back_populates="listings")
    product = relationship("Product", back_populates="listings")
    bundle = relationship("BundleSKU", back_populates="listings")
    sales = relationship("Sales", back_populates="listing")
    analysis_results = relationship("AnalysisResult", back_populates="listing")

    def __repr__(self):
        if self.product_type == 'single':
            return f"<Listing(account={self.account_id}, isbn='{self.isbn}', status='{self.coupang_status}')>"
        else:
            return f"<Listing(account={self.account_id}, bundle='{self.bundle_key}', status='{self.coupang_status}')>"

    @classmethod
    def create_from_product(cls, account_id, product, upload_method='csv'):
        """단권 상품으로부터 Listing 생성"""
        return cls(
            account_id=account_id,
            product_type='single',
            product_id=product.id,
            isbn=product.isbn,
            sale_price=product.sale_price,
            shipping_policy=product.shipping_policy,
            upload_method=upload_method,
            uploaded_at=datetime.utcnow()
        )

    @classmethod
    def create_from_bundle(cls, account_id, bundle, upload_method='csv'):
        """묶음 SKU로부터 Listing 생성"""
        return cls(
            account_id=account_id,
            product_type='bundle',
            bundle_id=bundle.id,
            bundle_key=bundle.bundle_key,
            sale_price=bundle.total_sale_price,
            shipping_policy=bundle.shipping_policy,
            upload_method=upload_method,
            uploaded_at=datetime.utcnow()
        )

    @property
    def is_active(self):
        """활성 상태인지"""
        return self.coupang_status == 'active'

    @property
    def is_pending(self):
        """대기 중인지"""
        return self.coupang_status == 'pending'

    def get_product_info(self, db_session):
        """상품 정보 조회 (단권/묶음 자동 판별)"""
        if self.product_type == 'single':
            return db_session.query(Product).get(self.product_id)
        else:
            return db_session.query(BundleSKU).get(self.bundle_id)
