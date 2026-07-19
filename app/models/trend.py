from sqlalchemy import Column, Float, Integer, String

from app.core.database import Base


class Trend(Base):
    __tablename__ = "trends"

    id = Column(Integer, primary_key=True, index=True)
    topic = Column(String, index=True, nullable=False)
    score = Column(Float, default=0.0, nullable=False)
    source = Column(String, nullable=False)
