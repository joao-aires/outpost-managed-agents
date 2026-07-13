import json
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, JSON
from app.database import Base

class Agent(Base):
    __tablename__ = "agents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    model = Column(String(255), nullable=False, default="claude-3-5-sonnet-latest")
    system = Column(Text, nullable=True)
    tools = Column(JSON, nullable=True, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "model": self.model,
            "system": self.system,
            "tools": self.tools if isinstance(self.tools, list) else json.loads(self.tools or "[]"),
            "created_at": self.created_at.isoformat()
        }
