"""분석 결과 모델"""
from sqlalchemy import Column, Integer, Float, ForeignKey, Date, DateTime, String, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class AnalysisResult(Base):
    """판매 분석 결과"""

    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False, index=True)
    analysis_date = Column(Date, nullable=False, index=True)
    period_days = Column(Integer, default=7)
    total_views = Column(Integer)
    total_orders = Column(Integer)
    conversion_rate = Column(Float)  # 전환율 (%)
    problem_type = Column(String(50), index=True)  # exposure_low, conversion_low, normal
    priority_score = Column(Float, index=True)  # 우선순위 점수 (0-100)
    recommended_actions = Column(JSON)  # [{"action": "...", "reason": "..."}]
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    listing = relationship("Listing", back_populates="analysis_results")

    def __repr__(self):
        return f"<AnalysisResult(listing={self.listing_id}, problem='{self.problem_type}', priority={self.priority_score})>"
