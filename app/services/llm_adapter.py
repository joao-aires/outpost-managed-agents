import json
import logging
import httpx
from typing import Dict, List, Any, Optional

logger = logging.getLogger("outpost_cma.llm_adapter")

class OllamaLLMAdapter:
    """
    Adapter that translates Anthropic message requests to Ollama's /v1/chat/completions endpoint
    and normalizes tool call responses for the Outpost Orchestrator.
    """
    def __init__(self, base_url: str = "http://127.0.0.1:11434", default_model: str = "gemma4:e2b"):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        if not self.base_url.endswith("/v1"):
            self.api_url = f"{self.base_url}/v1/chat/completions"
        else:
            self.api_url = f"{self.base_url}/chat/completions"

    async def create_message(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 1024
    ) -> Dict[str, Any]:
        target_model = model if model and ("gemma" in model or "qwen" in model or "llama" in model) else self.default_model

        # Build OpenAI style messages list
        openai_messages = []
        if system:
            # Inject tool definitions and instructions into system prompt if model needs prompt guidance
            system_content = system
            if tools:
                tools_desc = json.dumps(tools, indent=2)
                system_content += f"\n\nAvailable Tools:\n{tools_desc}\n\nTo use a tool, respond with a JSON block: {{\\\"type\\\": \\\"tool_use\\\", \\\"name\\\": \\\"tool_name\\\", \\\"input\\\": {{...}}}}"
            openai_messages.append({"role": "system", "content": system_content})

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle multi-part text and tool_result blocks
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "tool_result":
                            tool_out = part.get("content", "")
                            text_parts.append(f"[Tool Result for {part.get('tool_use_id')}]: {tool_out}")
                    else:
                        text_parts.append(str(part))
                content = "\n".join(text_parts)
            openai_messages.append({"role": role, "content": str(content)})

        payload = {
            "model": target_model,
            "messages": openai_messages,
            "stream": False
        }

        logger.info(f"[Ollama Adapter] Sending request to {self.api_url} with model {target_model}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(self.api_url, json=payload)
            res.raise_for_status()
            data = res.json()

        choice = data["choices"][0]
        response_msg = choice["message"]
        content_text = response_msg.get("content", "") or ""

        # Parse tool calls from JSON response if present
        content_blocks = []
        parsed_tool = None
        try:
            if "{" in content_text and "}" in content_text:
                json_start = content_text.find("{")
                json_end = content_text.rfind("}") + 1
                json_str = content_text[json_start:json_end]
                parsed = json.loads(json_str)
                if parsed.get("type") == "tool_use" or "name" in parsed:
                    parsed_tool = {
                        "type": "tool_use",
                        "id": f"toolu_{data.get('id', 'ollama_01')[-8:]}",
                        "name": parsed.get("name"),
                        "input": parsed.get("input", {})
                    }
                    text_before = content_text[:json_start].strip()
                    if text_before:
                        content_blocks.append({"type": "text", "text": text_before})
                    content_blocks.append(parsed_tool)
        except Exception:
            pass

        if not parsed_tool:
            content_blocks.append({"type": "text", "text": content_text})

        # Return Anthropic-compatible message response structure
        return {
            "id": data.get("id", "msg_ollama"),
            "type": "message",
            "role": "assistant",
            "model": target_model,
            "content": content_blocks,
            "stop_reason": "tool_use" if parsed_tool else "end_turn",
            "usage": data.get("usage", {"input_tokens": 10, "output_tokens": 10})
        }
