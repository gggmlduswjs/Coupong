"""묶음 SKU 모델"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base
from app.constants import BOOK_DISCOUNT_RATE, DEFAULT_SHIPPING_COST, FREE_SHIPPING_THRESHOLD


class BundleSKU(Base):
    """묶음 상품 (저마진 도서를 묶어서 무료배송 가능하게)"""
    __tablename__ = "bundle_skus"

    id = Column(Integer, primary_key=True, index=True)

    # 묶음 식별
    bundle_key = Column(String(200), unique=True, nullable=False, index=True)  # (publisher_id, normalized_series, year)
    bundle_name = Column(String(300), nullable=False)  # "개념원리 수학 3종 세트 (2025)"

    # 출판사/시리즈
    publisher_id = Column(Integer, ForeignKey('publishers.id'), nullable=False, index=True)
    normalized_series = Column(String(200), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)

    # 구성
    book_count = Column(Integer, nullable=False)  # 묶음 권수

    # 가격 (도서정가제)
    total_list_price = Column(Integer, nullable=False)  # 정가 합계
    total_sale_price = Column(Integer, nullable=False)  # 판매가 합계 (정가 × 0.9)

    # 마진 분석
    supply_rate = Column(Float, nullable=False)
    total_margin = Column(Integer, nullable=False)  # 총 마진
    shipping_cost = Column(Integer, default=DEFAULT_SHIPPING_COST)
    net_margin = Column(Integer, nullable=False)  # 순마진

    # 배송 정책
    shipping_policy = Column(String(20), default='free')  # 묶음은 기본 무료배송

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    publisher = relationship("Publisher", back_populates="bundle_skus")
    listings = relationship("Listing", back_populates="bundle")
    items = relationship("BundleItem", back_populates="bundle", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<BundleSKU(bundle_key='{self.bundle_key}', count={self.book_count}, net_margin={self.net_margin})>"

    @classmethod
    def create_bundle(cls, books, publisher, year, normalized_series):
        """
        도서 리스트로부터 묶음 SKU 생성

        주의: BundleItem 레코드는 별도로 생성해야 함 (bundle.id 필요)
        """
        if not books:
            raise ValueError("도서가 없습니다")

        # 묶음 키 생성
        bundle_key = f"{publisher.id}_{normalized_series}_{year}"

        # 도서 정보 수집
        total_list_price = sum(book.list_price for book in books)

        # 묶음명 생성
        bundle_name = f"{normalized_series} {len(books)}종 세트 ({year})"

        # 가격 계산 (도서정가제)
        total_sale_price = int(total_list_price * BOOK_DISCOUNT_RATE)

        # 마진 계산
        margin_info = publisher.calculate_margin(total_list_price)

        bundle = cls(
            bundle_key=bundle_key,
            bundle_name=bundle_name,
            publisher_id=publisher.id,
            normalized_series=normalized_series,
            year=year,
            book_count=len(books),
            total_list_price=total_list_price,
            total_sale_price=total_sale_price,
            supply_rate=publisher.supply_rate,
            total_margin=margin_info['margin_per_unit'],
            shipping_cost=margin_info['shipping_cost'],
            net_margin=margin_info['net_margin'],
            shipping_policy='free' if margin_info['net_margin'] >= FREE_SHIPPING_THRESHOLD else 'paid',
        )

        return bundle

    def get_book_ids(self):
        """items relationship에서 book_id 리스트 반환"""
        return [item.book_id for item in self.items]

    def get_isbns(self):
        """items relationship에서 isbn 리스트 반환"""
        return [item.isbn for item in self.items]

    @property
    def is_profitable(self):
        """수익성 있는 묶음인지"""
        return self.net_margin >= 0

    @property
    def is_free_shipping_eligible(self):
        """무료배송 가능 묶음인지"""
        return self.net_margin >= FREE_SHIPPING_THRESHOLD

    def is_uploaded_to_account(self, account_id, db_session):
        """특정 계정에 이미 업로드되었는지 체크"""
        from app.models.listing import Listing

        existing = db_session.query(Listing).filter(
            Listing.account_id == account_id,
            Listing.bundle_id == self.id
        ).first()

        return existing is not None

    def get_available_accounts(self, account_ids, db_session):
        """업로드 가능한 계정 리스트 (중복 제외)"""
        from app.models.listing import Listing

        # 이미 업로드된 계정 조회
        uploaded_accounts = db_session.query(Listing.account_id).filter(
            Listing.bundle_id == self.id,
            Listing.account_id.in_(account_ids)
        ).all()

        uploaded_account_ids = {acc[0] for acc in uploaded_accounts}

        # 업로드 가능한 계정 반환
        available = [acc_id for acc_id in account_ids if acc_id not in uploaded_account_ids]

        return available

    def to_csv_row(self):
        """CSV 업로드용 데이터 변환"""
        return {
            'bundle_key': self.bundle_key,
            'bundle_name': self.bundle_name,
            'isbns': self.get_isbns(),
            'book_count': self.book_count,
            'sale_price': self.total_sale_price,
            'list_price': self.total_list_price,
            'shipping_policy': '무료배송' if self.shipping_policy == 'free' else '유료배송',
            'stock_quantity': 5,
            'net_margin': self.net_margin
        }
