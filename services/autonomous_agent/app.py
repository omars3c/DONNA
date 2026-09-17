import os
import uuid
import traceback
import asyncio
import json
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from google import genai
from google.genai import types

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from shared.config import AUTONOMOUS_PORT, AUTONOMOUS_HOST, API_KEYS_PATH
from shared.error_reporter import install_sentinel
from services.brain_orchestrator.app import TOOL_DECLARATIONS
from services.brain_orchestrator.client_bridge import bridge

# --- Task Manager ---
class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}
    
    def create_task(self, description: str) -> str:
        task_id = str(uuid.uuid4())
        self.tasks[task_id] = {
            "id": task_id,
            "description": description,
            "status": "pending",
            "result": None,
            "steps": [],
            "error": None
        }
        return task_id
        
    def get_task(self, task_id: str) -> Dict[str, Any]:
        return self.tasks.get(task_id)
        
    def update_status(self, task_id: str, status: str, result: str = None, error: str = None):
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = status
            if result:
                self.tasks[task_id]["result"] = result
            if error:
                self.tasks[task_id]["error"] = error
                
    def add_step(self, task_id: str, step_info: dict):
        if task_id in self.tasks:
            self.tasks[task_id]["steps"].append(step_info)

task_manager = TaskManager()

# --- Agent Loop ---
SYSTEM_PROMPT = """You are D.O.N.N.A., an advanced autonomous AI agent.
You operate in a ReAct (Reasoning + Acting) loop.
Your goal is to complete the user's task using the available tools.
Think step-by-step.
When you are completely finished with the task, you MUST output a final summary starting with 'TASK_COMPLETE:'.
If you need more information, use a tool.
"""

class AgentLoop:
    async def run(self, task_id: str, goal: str, max_steps: int = 15):
        task_manager.update_status(task_id, "running")
        try:
            api_key = json.loads(API_KEYS_PATH.read_text(encoding="utf-8")).get("gemini_api_key", "")
            client = genai.Client(api_key=api_key)
            gemini_tools = [types.Tool(function_declarations=TOOL_DECLARATIONS)]
            chat = client.chats.create(
                model="gemini-3.6-flash",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=gemini_tools,
                    temperature=0.4
                )
            )
            prompt = f"Perform the following task autonomously. Output 'TASK_COMPLETE: <summary>' when done.\nTask: {goal}"
            
            for step in range(max_steps):
                print(f"[AgentLoop] Step {step+1}/{max_steps} for task {task_id}")
                response = chat.send_message(prompt)
                
                task_manager.add_step(task_id, {
                    "step": step + 1,
                    "text": response.text,
                    "function_calls": [fc.name for fc in response.function_calls] if response.function_calls else []
                })
                
                if response.text and "TASK_COMPLETE:" in response.text:
                    task_manager.update_status(task_id, "completed", result=response.text)
                    return
                
                if response.function_calls:
                    function_responses = []
                    for fc in response.function_calls:
                        name = fc.name
                        args = {k: v for k, v in fc.args.items()} if fc.args else {}
                        print(f"[AgentLoop] Calling tool: {name}")
                        try:
                            func = getattr(bridge, name, None)
                            if func:
                                if asyncio.iscoroutinefunction(func):
                                    res = await func(**args)
                                else:
                                    res = func(**args)
                                result_str = str(res)
                            else:
                                result_str = f"Error: Tool {name} not found."
                        except Exception as e:
                            result_str = f"Error executing {name}: {e}"
                        
                        function_responses.append(
                            types.Part.from_function_response(
                                name=name,
                                response={"result": result_str}
                            )
                        )
                    prompt = function_responses
                else:
                    prompt = "Please continue and use tools or output TASK_COMPLETE if you are done."
                    
            task_manager.update_status(task_id, "failed", error="Max steps reached")
        except Exception as e:
            traceback.print_exc()
            task_manager.update_status(task_id, "failed", error=str(e))

agent_loop = AgentLoop()

# --- FastAPI App ---
app = FastAPI(title="DONNA Autonomous Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
install_sentinel(app, "autonomous_agent")

class TaskRequest(BaseModel):
    task: str
    max_steps: int = 15

@app.get("/health")
def health():
    return {"status": "healthy", "service": "autonomous_agent", "port": AUTONOMOUS_PORT}

@app.post("/v1/task")
async def create_task(req: TaskRequest, background_tasks: BackgroundTasks):
    task_id = task_manager.create_task(req.task)
    background_tasks.add_task(agent_loop.run, task_id, req.task, req.max_steps)
    return {"status": "accepted", "task_id": task_id}

@app.get("/v1/task/{task_id}")
def get_task(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


