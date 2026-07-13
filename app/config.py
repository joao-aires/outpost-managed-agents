import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "OutpostManagedAgents"
    API_V1_STR: str = "/v1"
    
    # Anthropic Credentials
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./outpost_managed_agents.db")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Kubernetes Configuration
    KUBERNETES_NAMESPACE: str = os.getenv("KUBERNETES_NAMESPACE", "agent-sandboxes")
    SANDBOX_IMAGE: str = os.getenv("SANDBOX_IMAGE", "ubuntu:22.04")
    WARM_POOL_SIZE: int = int(os.getenv("WARM_POOL_SIZE", "3"))
    
    # Egress Control
    DEFAULT_ALLOWED_EGRESS_DOMAINS: str = os.getenv("ALLOWED_EGRESS_DOMAINS", "api.github.com,github.com,pypi.org,files.pythonhosted.org")

    class Config:
        case_sensitive = True

settings = Settings()
