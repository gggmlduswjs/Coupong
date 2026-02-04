"""작업 로그 모델"""
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from datetime import datetime
from app.database import Base


class Task(Base):
    """비동기 작업 로그"""

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String(50), nullable=False, index=True)  # crawl, upload, analyze
    status = Column(String(20), default="pending", index=True)  # pending, running, success, failed
    params = Column(JSON)  # 작업 파라미터
    result = Column(JSON)  # 작업 결과
    error_message = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<Task(type='{self.task_type}', status='{self.status}')>"
