import os
from pydantic_settings import BaseSettings
from pydantic import ConfigDict

class Settings(BaseSettings):
    model_config = ConfigDict(case_sensitive=True, extra="allow")

    PROJECT_NAME: str = "OutpostManagedAgents"
    API_V1_STR: str = "/v1"
    
    # LLM Credentials & Provider (Anthropic / Ollama / BYOB)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "anthropic") # anthropic, ollama, custom
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./outpost_managed_agents.db")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Kubernetes Configuration
    SANDBOX_DRIVER: str = os.getenv("SANDBOX_DRIVER", "direct") # direct, sigs-sandbox, or mock
    KUBERNETES_NAMESPACE: str = os.getenv("KUBERNETES_NAMESPACE", "agent-sandboxes")
    SANDBOX_IMAGE: str = os.getenv("SANDBOX_IMAGE", "outpost-sandbox:latest")
    WARM_POOL_SIZE: int = int(os.getenv("WARM_POOL_SIZE", "3"))
    
    # Egress Control
    DEFAULT_ALLOWED_EGRESS_DOMAINS: str = os.getenv("ALLOWED_EGRESS_DOMAINS", "api.github.com,github.com,pypi.org,files.pythonhosted.org")

settings = Settings()
