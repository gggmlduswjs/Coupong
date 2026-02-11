"""묶음 구성 아이템 모델 — 주문→책 분해의 핵심 테이블"""
from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.database import Base


class BundleItem(Base):
    """묶음 SKU를 구성하는 개별 도서"""

    __tablename__ = "bundle_items"
    __table_args__ = (
        UniqueConstraint("bundle_id", "book_id", name="uix_bundle_book"),
        Index("ix_bundle_item_book", "book_id"),
    )

    id = Column(Integer, primary_key=True)
    bundle_id = Column(Integer, ForeignKey("bundle_skus.id"), nullable=False)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    isbn = Column(String(13), nullable=False)

    # Relationships
    bundle = relationship("BundleSKU", back_populates="items")
    book = relationship("Book")

    def __repr__(self):
        return f"<BundleItem(bundle={self.bundle_id}, book={self.book_id}, isbn='{self.isbn}')>"
