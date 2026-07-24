import socket
import uvicorn
import threading
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Lightweight Local LLM Engine implementing Anthropic /v1/messages API for E2E testing
local_llm_app = FastAPI(title="Local LLM Engine")

def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

@local_llm_app.post("/v1/messages")
async def handle_messages(request: Request):
    data = await request.json()
    model = data.get("model", "local-llm")
    messages = data.get("messages", [])
    
    last_msg = messages[-1] if messages else {}
    last_content = last_msg.get("content", [])
    
    has_tool_result = False
    if isinstance(last_content, list):
        has_tool_result = any(
            isinstance(block, dict) and block.get("type") == "tool_result" 
            for block in last_content
        )
        
    if has_tool_result:
        return JSONResponse({
            "id": "msg_local_llm_final",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [
                {
                    "type": "text",
                    "text": "I have executed the requested harness tool task successfully."
                }
            ],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 15, "output_tokens": 20}
        })
    else:
        return JSONResponse({
            "id": "msg_local_llm_tool",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [
                {
                    "type": "text",
                    "text": "Executing environment tool setup..."
                },
                {
                    "type": "tool_use",
                    "id": "toolu_local_01",
                    "name": "write_file",
                    "input": {
                        "path": "/workspace/e2e_test_output.txt",
                        "content": "E2E Local LLM Agent Execution Verified!"
                    }
                }
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 10, "output_tokens": 25}
        })

class LocalLLMServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port if port != 0 else get_free_port()
        self.server = None
        self.thread = None

    def start(self):
        config = uvicorn.Config(local_llm_app, host=self.host, port=self.port, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.should_exit = True
