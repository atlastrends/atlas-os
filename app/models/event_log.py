from sqlalchemy import Column, Integer, String

from app.core.database import Base


class EventLog(Base):
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, nullable=False)
    message = Column(String, nullable=False)
