"""판매 데이터 모델"""
from sqlalchemy import Column, Integer, ForeignKey, Date, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Sales(Base):
    """판매 데이터"""

    __tablename__ = "sales"
    __table_args__ = (UniqueConstraint("listing_id", "date", name="uix_listing_date"),)

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    views = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    orders = Column(Integer, default=0)
    revenue = Column(Integer, default=0)
    refunds = Column(Integer, default=0)
    stock = Column(Integer, default=0)
    ranking = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    listing = relationship("Listing", back_populates="sales")

    def __repr__(self):
        return f"<Sales(listing={self.listing_id}, date={self.date}, orders={self.orders})>"
