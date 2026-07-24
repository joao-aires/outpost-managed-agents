from typing import List, Optional, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, ConfigDict

from app.database import get_db
from app.models.agent import Agent

router = APIRouter(prefix="/agents", tags=["agents"])

# Pydantic Schemas
class ToolSchema(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]

class AgentCreate(BaseModel):
    name: str
    model: str = "claude-3-5-sonnet-latest"
    harness: Optional[str] = "claude-code"  # claude-code, opencode, aider, cursor, custom
    system: Optional[str] = None
    skills: Optional[List[Dict[str, Any]]] = []
    tools: Optional[List[Dict[str, Any]]] = []
    environment: Optional[Dict[str, Any]] = {}
    agent_config: Optional[Dict[str, Any]] = {}

class AgentResponse(BaseModel):
    id: str
    name: str
    model: str
    harness: str
    system: Optional[str]
    skills: List[Dict[str, Any]]
    tools: List[Dict[str, Any]]
    environment: Dict[str, Any]
    agent_config: Dict[str, Any]
    created_at: str

    model_config = ConfigDict(from_attributes=True)

@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(agent_in: AgentCreate, db: AsyncSession = Depends(get_db)):
    """
    Creates a new agent configuration (equivalent to POST /v1/agents)
    """
    db_agent = Agent(
        name=agent_in.name,
        model=agent_in.model,
        harness=agent_in.harness or "claude-code",
        system=agent_in.system,
        skills=agent_in.skills or [],
        tools=agent_in.tools or [],
        environment=agent_in.environment or {},
        agent_config=agent_in.agent_config or {}
    )
    db.add(db_agent)
    await db.commit()
    await db.refresh(db_agent)
    
    return AgentResponse(**db_agent.to_dict())

@router.get("", response_model=List[AgentResponse])
async def list_agents(db: AsyncSession = Depends(get_db)):
    """
    Lists all agent configurations (equivalent to GET /v1/agents)
    """
    result = await db.execute(select(Agent))
    agents = result.scalars().all()
    return [AgentResponse(**a.to_dict()) for a in agents]

@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieves details of a specific agent configuration (equivalent to GET /v1/agents/{agent_id})
    """
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found"
        )
    return AgentResponse(**agent.to_dict())

@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """
    Deletes/Archives an agent configuration (equivalent to DELETE /v1/agents/{agent_id})
    """
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found"
        )
    await db.delete(agent)
    await db.commit()
    return None
