# Helper to load SQLAlchemy metadata for migration tools like Atlas
from app.database import Base
from app.models.agent import Agent
from app.models.session import Session

# Target metadata for schema reflection
metadata = Base.metadata
