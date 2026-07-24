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
    harness = Column(String(255), nullable=False, default="claude-code")  # claude-code, opencode, aider, cursor, custom
    system = Column(Text, nullable=True)
    skills = Column(JSON, nullable=True, default=list)
    tools = Column(JSON, nullable=True, default=list)
    environment = Column(JSON, nullable=True, default=dict)  # { base_image, env_vars, resources, init_script }
    agent_config = Column(JSON, nullable=True, default=dict) # { cli_flags, config_files }
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        def _parse_json(val, default):
            if val is None:
                return default
            if isinstance(val, (list, dict)):
                return val
            try:
                return json.loads(val)
            except Exception:
                return default

        created_dt = self.created_at or datetime.utcnow()

        return {
            "id": self.id,
            "name": self.name,
            "model": self.model or "claude-3-5-sonnet-latest",
            "harness": self.harness or "claude-code",
            "system": self.system,
            "skills": _parse_json(self.skills, []),
            "tools": _parse_json(self.tools, []),
            "environment": _parse_json(self.environment, {}),
            "agent_config": _parse_json(self.agent_config, {}),
            "created_at": created_dt.isoformat()
        }
