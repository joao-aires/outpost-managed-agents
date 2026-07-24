from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, ConfigDict

from app.database import get_db
from app.models.session import Session
from app.models.agent import Agent
from app.services.orchestrator import agent_orchestrator
from app.services.sandbox import sandbox_driver

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Pydantic Schemas
class SessionCreate(BaseModel):
    agent_id: str

class SessionResponse(BaseModel):
    id: str
    agent_id: str
    status: str
    pod_name: Optional[str]
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

class UserEventIn(BaseModel):
    message: str

@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(session_in: SessionCreate, db: AsyncSession = Depends(get_db)):
    """
    Creates a new agent session (equivalent to POST /v1/sessions)
    """
    result = await db.execute(select(Agent).where(Agent.id == session_in.agent_id))
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {session_in.agent_id} not found"
        )
    
    db_session = Session(
        agent_id=session_in.agent_id,
        status="idle"
    )
    db.add(db_session)
    await db.commit()
    await db.refresh(db_session)
    
    return SessionResponse(**db_session.to_dict())

@router.get("", response_model=List[SessionResponse])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    """
    Lists all sessions (equivalent to GET /v1/sessions)
    """
    result = await db.execute(select(Session))
    sessions = result.scalars().all()
    return [SessionResponse(**s.to_dict()) for s in sessions]

@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieves details of a specific session (equivalent to GET /v1/sessions/{session_id})
    """
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalars().first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID {session_id} not found"
        )
    return SessionResponse(**session.to_dict())

@router.post("/{session_id}/events", status_code=status.HTTP_202_ACCEPTED)
async def send_session_event(
    session_id: str,
    event_in: UserEventIn,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Sends a message to the session execution queue (equivalent to POST /v1/sessions/{session_id}/events)
    """
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalars().first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID {session_id} not found"
        )
    
    background_tasks.add_task(
        agent_orchestrator.run_session_turn,
        session_id=session_id,
        message=event_in.message,
        db=db
    )
    
    return {"status": "event_received"}

@router.get("/{session_id}/events", response_class=StreamingResponse)
async def stream_session_events(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Establishes a real-time SSE stream of session outputs (equivalent to GET /v1/sessions/{session_id}/events/stream)
    """
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalars().first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID {session_id} not found"
        )
    
    async def sse_generator():
        async for event in agent_orchestrator.get_stream_generator(session_id):
            yield f"event: {event['event']}\ndata: {event['data']}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")

@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Terminates a session and cleans up its Kubernetes sandbox
    """
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalars().first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID {session_id} not found"
        )
    
    if session.pod_name:
        await sandbox_driver.delete_sandbox(session.pod_name)
        
    await db.delete(session)
    await db.commit()
    return None
