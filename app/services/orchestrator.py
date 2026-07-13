import json
import asyncio
import logging
from typing import Dict, List, Any, AsyncGenerator
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from anthropic import AsyncAnthropic, APIError

from app.config import settings
from app.models.agent import Agent
from app.models.session import Session
from app.services.kubernetes import sandbox_client

logger = logging.getLogger("outpost_cma.orchestrator")

# In-memory pub-sub for SSE streaming per session
class SessionPubSub:
    def __init__(self):
        self.listeners: Dict[str, List[asyncio.Queue]] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue:
        queue = asyncio.Queue()
        if session_id not in self.listeners:
            self.listeners[session_id] = []
        self.listeners[session_id].append(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue):
        if session_id in self.listeners:
            self.listeners[session_id].remove(queue)
            if not self.listeners[session_id]:
                del self.listeners[session_id]

    async def publish(self, session_id: str, event_type: str, data: Any):
        if session_id in self.listeners:
            event_payload = {
                "event": event_type,
                "data": json.dumps(data)
            }
            for queue in self.listeners[session_id]:
                await queue.put(event_payload)

session_bus = SessionPubSub()

class AgentOrchestrator:
    """
    Orchestrates the LLM reasoning loop and maps tool calls to Kubernetes pod sandboxes.
    """
    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY) if settings.ANTHROPIC_API_KEY else None
        # In-memory conversation history store (Simplification of session logs)
        self.history_store: Dict[str, List[Dict[str, Any]]] = {}

    async def run_session_turn(self, session_id: str, message: str, db: AsyncSession):
        """
        Runs one interaction turn. Triggers the Agent Loop.
        """
        # Fetch Session and Agent configuration
        result = await db.execute(select(Session).where(Session.id == session_id))
        session = result.scalars().first()
        if not session:
            logger.error(f"Session {session_id} not found.")
            return

        result = await db.execute(select(Agent).where(Agent.id == session.agent_id))
        agent = result.scalars().first()
        if not agent:
            logger.error(f"Agent associated with session {session_id} not found.")
            return

        # Ensure Sandbox is provisioned
        if not session.pod_name:
            session.status = "provisioning"
            await db.commit()
            await session_bus.publish(session_id, "session.status_change", {"status": "provisioning"})
            
            try:
                pod_name = await sandbox_client.create_sandbox_pod(session_id)
                session.pod_name = pod_name
                session.status = "running"
                await db.commit()
                await session_bus.publish(session_id, "session.status_change", {"status": "running", "pod_name": pod_name})
            except Exception as e:
                session.status = "failed"
                await db.commit()
                await session_bus.publish(session_id, "session.error", {"message": f"Failed to provision sandbox: {str(e)}"})
                return

        # Initialize History
        if session_id not in self.history_store:
            self.history_store[session_id] = []

        # Add user message to history
        self.history_store[session_id].append({"role": "user", "content": message})
        await session_bus.publish(session_id, "user.message", {"text": message})

        # Run Loop
        asyncio.create_task(self._agent_loop(session, agent, db))

    async def _agent_loop(self, session: Session, agent: Agent, db: AsyncSession):
        session_id = session.id
        pod_name = session.pod_name
        history = self.history_store[session_id]

        if not self.client:
            await session_bus.publish(session_id, "session.error", {
                "message": "Anthropic API Key not configured on server. Cannot run agent loop."
            })
            session.status = "idle"
            await db.commit()
            return

        # Map tools config from Agent db schema
        agent_tools = agent.tools if isinstance(agent.tools, list) else json.loads(agent.tools or "[]")
        
        # Inject standard built-in tools (bash, write_file, read_file) if none are defined
        if not agent_tools:
            agent_tools = [
                {
                    "name": "bash",
                    "description": "Execute a shell command inside the Kubernetes sandbox. Returns stdout/stderr.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "The bash shell command to run."}
                        },
                        "required": ["command"]
                    }
                },
                {
                    "name": "write_file",
                    "description": "Create or overwrite a file in the sandbox filesystem.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "The absolute filepath (e.g. /workspace/script.sh)."},
                            "content": {"type": "string", "description": "The text content of the file."}
                        },
                        "required": ["path", "content"]
                    }
                },
                {
                    "name": "read_file",
                    "description": "Read the contents of a file from the sandbox filesystem.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "The absolute filepath to read."}
                        },
                        "required": ["path"]
                    }
                }
            ]

        loop_count = 0
        max_loops = 15

        while loop_count < max_loops:
            loop_count += 1
            try:
                # Call Anthropic with streaming enabled
                logger.info(f"Invoking LLM for session {session_id} (loop {loop_count})")
                
                # Format system prompt
                system_prompt = agent.system or "You are a helpful assistant running in a secure sandbox environment."
                
                # We need to translate custom tools into Anthropic tool models
                formatted_tools = []
                for tool in agent_tools:
                    formatted_tools.append({
                        "name": tool["name"],
                        "description": tool["description"],
                        "input_schema": tool["input_schema"]
                    })

                # Call Anthropic API
                response = await self.client.messages.create(
                    model=agent.model,
                    max_tokens=4000,
                    system=system_prompt,
                    messages=history,
                    tools=formatted_tools
                )

                # Process the response content
                assistant_content = []
                tool_calls = []

                # Accumulate content blocks
                for block in response.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                        # Publish delta / start message
                        await session_bus.publish(session_id, "agent.message", {"text": block.text})
                    elif block.type == "tool_use":
                        tool_calls.append(block)
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input
                        })
                        await session_bus.publish(session_id, "agent.tool_use", {
                            "id": block.id,
                            "name": block.name,
                            "input": block.input
                        })

                # Append assistant turn to history
                history.append({"role": "assistant", "content": assistant_content})

                # If no tool calls, loop completes
                if not tool_calls:
                    logger.info(f"Agent finished reasoning for session {session_id}")
                    break

                # Execute each tool call inside the Pod Sandbox
                tool_results_content = []
                for tool_call in tool_calls:
                    tool_id = tool_call.id
                    tool_name = tool_call.name
                    tool_input = tool_call.input

                    logger.info(f"Executing tool {tool_name} for session {session_id} on pod {pod_name}")
                    
                    result_text = ""
                    is_error = False

                    try:
                        if tool_name == "bash":
                            cmd = tool_input.get("command")
                            exec_res = await sandbox_client.execute_command(pod_name, cmd)
                            result_text = f"stdout:\n{exec_res['stdout']}\nstderr:\n{exec_res['stderr']}\nexit_code: {exec_res['exit_code']}"
                        elif tool_name == "write_file":
                            path = tool_input.get("path")
                            content = tool_input.get("content", "")
                            success = await sandbox_client.write_file(pod_name, path, content.encode("utf-8"))
                            result_text = "File successfully written." if success else "Failed to write file."
                        elif tool_name == "read_file":
                            path = tool_input.get("path")
                            file_content = await sandbox_client.read_file(pod_name, path)
                            result_text = file_content.decode("utf-8", errors="replace")
                        else:
                            # Catch custom registered tools or placeholders
                            result_text = f"Tool {tool_name} not natively implemented. Execution bypassed."
                    except Exception as e:
                        logger.error(f"Error running tool {tool_name}: {e}")
                        result_text = f"Execution error: {str(e)}"
                        is_error = True

                    # Publish tool result
                    await session_bus.publish(session_id, "agent.tool_result", {
                        "id": tool_id,
                        "output": result_text,
                        "is_error": is_error
                    })

                    # Add tool response block
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_text,
                        "is_error": is_error
                    })

                # Append tool result to history
                history.append({"role": "user", "content": tool_results_content})

            except APIError as e:
                logger.error(f"Anthropic API Error: {e}")
                await session_bus.publish(session_id, "session.error", {"message": f"Anthropic API error: {str(e)}"})
                break
            except Exception as e:
                logger.error(f"Unexpected error in agent loop: {e}")
                await session_bus.publish(session_id, "session.error", {"message": f"Orchestration runtime error: {str(e)}"})
                break

        # Finished run loop -> Set status back to idle
        session.status = "idle"
        await db.commit()
        await session_bus.publish(session_id, "session.status_change", {"status": "idle"})

    async def get_stream_generator(self, session_id: str) -> AsyncGenerator[Dict[str, str], None]:
        """
        Creates an SSE event generator for client connection.
        """
        queue = session_bus.subscribe(session_id)
        try:
            # Yield past message histories or a connection confirmation event
            yield {"event": "connection.established", "data": json.dumps({"session_id": session_id})}
            
            while True:
                # Listen to new events published by agent loop
                event = await queue.get()
                yield event
                queue.task_done()
        except asyncio.CancelledError:
            pass
        finally:
            session_bus.unsubscribe(session_id, queue)

# Singleton Instance
agent_orchestrator = AgentOrchestrator()
