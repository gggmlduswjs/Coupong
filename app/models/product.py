"""단권 상품 모델"""
from sqlalchemy import Column, Integer, String, Boolean, Text, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base
from app.constants import DEFAULT_SHIPPING_COST, DEFAULT_STOCK


class Product(Base):
    """단권 상품 (마진/배송 정보 포함)"""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)

    # 도서 참조
    book_id = Column(Integer, ForeignKey('books.id'), nullable=False, index=True)
    isbn = Column(String(13), nullable=False, index=True)

    # 가격 (도서정가제)
    list_price = Column(Integer, nullable=False)  # 정가
    sale_price = Column(Integer, nullable=False)  # 판매가 (정가 × 0.9)

    # 마진 분석
    supply_rate = Column(Float, nullable=False)  # 공급률 (0.27~0.60)
    margin_per_unit = Column(Integer, nullable=False)  # 권당 마진 (원)
    shipping_cost = Column(Integer, default=DEFAULT_SHIPPING_COST)  # 배송비 (원)
    net_margin = Column(Integer, nullable=False)  # 순마진 (마진 - 배송비)

    # 배송 정책
    shipping_policy = Column(String(20), nullable=False, index=True)  # 'free', 'paid', 'bundle_required'
    can_upload_single = Column(Boolean, default=True)  # 단권 업로드 가능 여부

    # 상태
    status = Column(String(20), default='ready', index=True)  # ready, uploaded, excluded
    exclude_reason = Column(Text)  # 제외 사유

    # 등록 승인 상태
    registration_status = Column(String(20), default='pending_review', index=True)  # pending_review, approved, rejected

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    book = relationship("Book", back_populates="products")
    listings = relationship("Listing", back_populates="product")

    def __repr__(self):
        return f"<Product(isbn='{self.isbn}', net_margin={self.net_margin}, policy='{self.shipping_policy}')>"

    @classmethod
    def create_from_book(cls, book, publisher):
        """
        Book과 Publisher로부터 Product 생성

        Args:
            book: Book 인스턴스
            publisher: Publisher 인스턴스

        Returns:
            Product 인스턴스
        """
        # 마진 계산
        margin_info = publisher.calculate_margin(book.list_price)

        # 배송 정책 결정
        shipping_policy = publisher.determine_shipping_policy(book.list_price)
        can_upload_single = publisher.can_upload_single(book.list_price)

        product = cls(
            book_id=book.id,
            isbn=book.isbn,
            list_price=book.list_price,
            sale_price=margin_info['sale_price'],
            supply_rate=publisher.supply_rate,
            margin_per_unit=margin_info['margin_per_unit'],
            shipping_cost=margin_info['shipping_cost'],
            net_margin=margin_info['net_margin'],
            shipping_policy=shipping_policy,
            can_upload_single=can_upload_single,
            status='ready'
        )

        # 단권 업로드 불가능하면 제외 사유 기록
        if not can_upload_single:
            product.status = 'excluded'
            product.exclude_reason = f'순마진 부족 ({margin_info["net_margin"]:,}원 < 0원). 묶음 SKU 필요.'

        return product

    @property
    def is_pending_review(self):
        """검토 대기 중인 상품인지"""
        return self.registration_status == 'pending_review'

    @property
    def is_approved(self):
        """승인된 상품인지"""
        return self.registration_status == 'approved'

    @property
    def can_upload(self):
        """업로드 가능한 상품인지 (ready + 승인 + 단권가능)"""
        return self.status == 'ready' and self.registration_status == 'approved' and self.can_upload_single

    @property
    def is_profitable(self):
        """수익성 있는 상품인지"""
        return self.net_margin >= 0

    @property
    def is_free_shipping_eligible(self):
        """무료배송 가능 상품인지"""
        return self.shipping_policy == 'free'

    def is_uploaded_to_account(self, account_id, db_session):
        """특정 계정에 이미 업로드되었는지 체크"""
        from app.models.listing import Listing

        existing = db_session.query(Listing).filter(
            Listing.account_id == account_id,
            Listing.isbn == self.isbn
        ).first()

        return existing is not None

    def get_available_accounts(self, account_ids, db_session):
        """업로드 가능한 계정 리스트 (중복 제외)"""
        from app.models.listing import Listing

        # 이미 업로드된 계정 조회
        uploaded_accounts = db_session.query(Listing.account_id).filter(
            Listing.isbn == self.isbn,
            Listing.account_id.in_(account_ids)
        ).all()

        uploaded_account_ids = {acc[0] for acc in uploaded_accounts}

        # 업로드 가능한 계정 반환
        available = [acc_id for acc_id in account_ids if acc_id not in uploaded_account_ids]

        return available

    def to_csv_row(self):
        """CSV 업로드용 데이터 변환"""
        return {
            'isbn': self.isbn,
            'sale_price': self.sale_price,
            'list_price': self.list_price,
            'shipping_policy': '무료배송' if self.shipping_policy == 'free' else '유료배송',
            'stock_quantity': DEFAULT_STOCK,
            'net_margin': self.net_margin
        }
