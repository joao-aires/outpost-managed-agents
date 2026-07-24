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
from app.services.sandbox import sandbox_driver
from app.services.harness.factory import HarnessDriverFactory

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
    Orchestrates the LLM reasoning loop, harness initialization, and maps tool calls to sandbox runtimes.
    """
    def __init__(self):
        # Support BYOB (Bring Your Own Brain) custom base_url if configured
        base_url = getattr(settings, "LLM_BASE_URL", None) or None
        api_key = settings.ANTHROPIC_API_KEY or "mock-key-for-local-testing"
        self.client = AsyncAnthropic(api_key=api_key, base_url=base_url)
        self.history_store: Dict[str, List[Dict[str, Any]]] = {}
        self.harness_initialized: Dict[str, bool] = {}

    async def _call_llm(self, model: str, system_prompt: str, history: list, tools: list):
        base_url = getattr(settings, "LLM_BASE_URL", "") or ""
        provider = getattr(settings, "LLM_PROVIDER", "").lower()
        
        if "11434" in base_url or provider == "ollama":
            from app.services.llm_adapter import OllamaLLMAdapter
            adapter = OllamaLLMAdapter(base_url=base_url or "http://127.0.0.1:11434")
            raw_msg = await adapter.create_message(
                model=model,
                messages=history,
                system=system_prompt,
                tools=tools
            )

            class Block:
                def __init__(self, d):
                    self.type = d.get("type")
                    self.text = d.get("text", "")
                    self.id = d.get("id")
                    self.name = d.get("name")
                    self.input = d.get("input")

            class AnthropicLikeResponse:
                def __init__(self, raw):
                    self.content = [Block(b) for b in raw.get("content", [])]

            return AnthropicLikeResponse(raw_msg)
        else:
            return await self.client.messages.create(
                model=model,
                max_tokens=4000,
                system=system_prompt,
                messages=history,
                tools=tools
            )

    async def run_session_turn(self, session_id: str, message: str, db: AsyncSession):
        """
        Runs one interaction turn. Triggers the Agent Loop.
        """
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
                pod_name = await sandbox_driver.create_sandbox(session_id)
                session.pod_name = pod_name
                session.status = "running"
                await db.commit()
                await session_bus.publish(session_id, "session.status_change", {"status": "running", "pod_name": pod_name})
            except Exception as e:
                session.status = "failed"
                await db.commit()
                await session_bus.publish(session_id, "session.error", {"message": f"Failed to provision sandbox: {str(e)}"})
                return

        # Provision Harness files & initialization script if not already done
        if not self.harness_initialized.get(session_id):
            await self._provision_harness(session.pod_name, agent)
            self.harness_initialized[session_id] = True

        # Initialize History
        if session_id not in self.history_store:
            self.history_store[session_id] = []

        # Add user message to history
        self.history_store[session_id].append({"role": "user", "content": message})
        await session_bus.publish(session_id, "user.message", {"text": message})

        # Run Loop
        asyncio.create_task(self._agent_loop(session, agent, db))

    async def _provision_harness(self, pod_name: str, agent: Agent):
        """
        Injects harness configuration, skills, tools, and executes the harness init script inside the sandbox.
        """
        driver = HarnessDriverFactory.get_driver(agent.harness)
        logger.info(f"Provisioning harness '{driver.harness_name}' for agent {agent.id} on sandbox {pod_name}")

        agent_dict = agent.to_dict()
        agent_config = agent_dict.get("agent_config", {})
        environment = agent_dict.get("environment", {})
        skills = agent_dict.get("skills", [])

        # 1. Inject Config Files (.claude.json, opencode.json, etc.)
        config_files = driver.get_config_files(agent_config, agent.system)
        for path, content in config_files.items():
            await sandbox_driver.write_file(pod_name, path, content.encode("utf-8"))

        # 2. Inject Skills
        skill_files = driver.prepare_skills(skills)
        for path, content in skill_files.items():
            await sandbox_driver.write_file(pod_name, path, content.encode("utf-8"))

        # 3. Execute Init Script
        init_script = driver.get_init_script(agent_config, environment)
        if init_script:
            init_path = "/tmp/outpost_harness_init.sh"
            await sandbox_driver.write_file(pod_name, init_path, init_script.encode("utf-8"))
            await sandbox_driver.execute_command(pod_name, f"chmod +x {init_path} && {init_path}")

    async def _agent_loop(self, session: Session, agent: Agent, db: AsyncSession):
        session_id = session.id
        pod_name = session.pod_name
        history = self.history_store[session_id]

        if not self.client:
            await session_bus.publish(session_id, "session.error", {
                "message": "LLM client not configured on server."
            })
            session.status = "idle"
            await db.commit()
            return

        agent_dict = agent.to_dict()
        raw_tools = agent_dict.get("tools", [])
        driver = HarnessDriverFactory.get_driver(agent.harness)
        agent_tools = driver.prepare_tools(raw_tools)

        loop_count = 0
        max_loops = 15

        while loop_count < max_loops:
            loop_count += 1
            try:
                logger.info(f"Invoking LLM for session {session_id} (loop {loop_count})")
                system_prompt = agent.system or "You are a helpful assistant running in a secure sandbox environment."
                
                formatted_tools = []
                for tool in agent_tools:
                    formatted_tools.append({
                        "name": tool["name"],
                        "description": tool["description"],
                        "input_schema": tool["input_schema"]
                    })

                response = await self._call_llm(
                    model=agent.model,
                    system_prompt=system_prompt,
                    history=history,
                    tools=formatted_tools
                )

                assistant_content = []
                tool_calls = []

                for block in response.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
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

                history.append({"role": "assistant", "content": assistant_content})

                if not tool_calls:
                    logger.info(f"Agent finished reasoning for session {session_id}")
                    break

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
                            exec_res = await sandbox_driver.execute_command(pod_name, cmd)
                            result_text = f"stdout:\n{exec_res['stdout']}\nstderr:\n{exec_res['stderr']}\nexit_code: {exec_res['exit_code']}"
                        elif tool_name == "write_file":
                            path = tool_input.get("path") or tool_input.get("filepath") or tool_input.get("file_path") or tool_input.get("filename") or "/workspace/output.txt"
                            content = tool_input.get("content") or tool_input.get("text") or tool_input.get("code") or ""
                            success = await sandbox_driver.write_file(pod_name, path, content.encode("utf-8"))
                            result_text = f"File {path} successfully written." if success else f"Failed to write file {path}."
                        elif tool_name == "read_file":
                            path = tool_input.get("path") or tool_input.get("filepath") or tool_input.get("file_path") or tool_input.get("filename") or "/workspace/output.txt"
                            file_content = await sandbox_driver.read_file(pod_name, path)
                            result_text = file_content.decode("utf-8", errors="replace")
                        else:
                            result_text = f"Tool {tool_name} executed."
                    except Exception as e:
                        logger.error(f"Error running tool {tool_name}: {e}")
                        result_text = f"Execution error: {str(e)}"
                        is_error = True

                    await session_bus.publish(session_id, "agent.tool_result", {
                        "id": tool_id,
                        "output": result_text,
                        "is_error": is_error
                    })

                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_text,
                        "is_error": is_error
                    })

                history.append({"role": "user", "content": tool_results_content})

            except APIError as e:
                logger.error(f"Anthropic API Error: {e}")
                await session_bus.publish(session_id, "session.error", {"message": f"Anthropic API error: {str(e)}"})
                break
            except Exception as e:
                logger.error(f"Unexpected error in agent loop: {e}")
                await session_bus.publish(session_id, "session.error", {"message": f"Orchestration runtime error: {str(e)}"})
                break

        s_obj = await db.scalar(select(Session).where(Session.id == session_id))
        if s_obj:
            s_obj.status = "idle"
            await db.commit()
        await session_bus.publish(session_id, "session.status_change", {"status": "idle"})

    async def get_stream_generator(self, session_id: str) -> AsyncGenerator[Dict[str, str], None]:
        queue = session_bus.subscribe(session_id)
        try:
            yield {"event": "connection.established", "data": json.dumps({"session_id": session_id})}
            
            while True:
                event = await queue.get()
                yield event
                queue.task_done()
        except asyncio.CancelledError:
            pass
        finally:
            session_bus.unsubscribe(session_id, queue)

agent_orchestrator = AgentOrchestrator()
