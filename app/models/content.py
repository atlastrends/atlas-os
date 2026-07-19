from sqlalchemy import Column, Float, Integer, String

from app.core.database import Base


class Content(Base):
    __tablename__ = "contents"

    id = Column(Integer, primary_key=True, index=True)
    topic = Column(String, nullable=False)
    language = Column(String, nullable=False)
    script = Column(String, nullable=True)
    performance_score = Column(Float, default=0.0, nullable=False)
