"""계정 모델"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Account(Base):
    """쿠팡 계정 정보"""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_name = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), nullable=False)
    password_encrypted = Column(String(500), nullable=False)
    session_file = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    listings = relationship("Listing", back_populates="account")

    def __repr__(self):
        return f"<Account(name='{self.account_name}', email='{self.email}')>"
