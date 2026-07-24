import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey
from app.database import Base

class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False)
    status = Column(String(50), default="idle")  # idle, running, completed, failed
    pod_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        created_dt = self.created_at or datetime.utcnow()
        updated_dt = self.updated_at or datetime.utcnow()

        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "status": self.status,
            "pod_name": self.pod_name,
            "created_at": created_dt.isoformat(),
            "updated_at": updated_dt.isoformat()
        }
