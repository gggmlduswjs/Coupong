"""교보문고 크롤링 데이터 모델"""
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Boolean
from datetime import datetime
from app.database import Base


class KyoboProduct(Base):
    """교보문고 크롤링 원본 데이터"""

    __tablename__ = "kyobo_products"

    id = Column(Integer, primary_key=True, index=True)
    isbn = Column(String(13), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=False)
    author = Column(String(200))
    publisher = Column(String(100))
    publish_date = Column(Date)
    original_price = Column(Integer, nullable=False)
    category = Column(String(100))
    subcategory = Column(String(100))
    image_url = Column(Text)
    description = Column(Text)
    kyobo_url = Column(Text)
    crawled_at = Column(DateTime, default=datetime.utcnow, index=True)
    is_processed = Column(Boolean, default=False, index=True)

    def __repr__(self):
        return f"<KyoboProduct(isbn='{self.isbn}', title='{self.title[:30]}...')>"
