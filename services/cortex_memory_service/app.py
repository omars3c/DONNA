"""
Cortex Memory Microservice (Port 8002)
Standalone FastAPI service managing SQLite vector store, semantic recall, tasks, and journal.
"""

import sys
from pathlib import Path

# Add project root to sys.path so modules can be imported smoothly
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from shared.models.memory import (
    RecallRequest,
    RecallResponse,
    SaveKnowledgeRequest,
    SaveKnowledgeResponse,
    TaskActionRequest,
    TaskResponse,
    JournalRequest,
    JournalResponse,
)
from shared.config import CORTEX_PORT, CORTEX_HOST
from memory.cortex_engine import cortex
from actions.cortex_memory import recall_memory, save_knowledge, manage_cortex_tasks

app = FastAPI(
    title="DONNA Cortex Memory Service",
    description="Vector Knowledge Graph, Semantic Search, and Task Engine",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "cortex_memory_service",
        "port": CORTEX_PORT,
    }


@app.post("/v1/memory/recall", response_model=RecallResponse)
def api_recall_memory(req: RecallRequest):
    try:
        raw_results = cortex.search_nodes(
            query=req.query,
            category=req.category or "all",
            limit=req.limit or 5,
        )
        formatted_str = recall_memory(
            query=req.query,
            category=req.category,
            limit=req.limit,
        )
        return RecallResponse(
            query=req.query,
            count=len(raw_results),
            results=raw_results,
            formatted=formatted_str,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/memory/save", response_model=SaveKnowledgeResponse)
def api_save_knowledge(req: SaveKnowledgeRequest):
    try:
        node_id = cortex.store_node(
            title=req.title or req.content[:40],
            content=req.content,
            category=req.category,
            tags=req.tags,
            importance=req.importance,
        )
        msg = f"Knowledge saved [ID #{node_id}, Category: {req.category}]: '{req.title}'."
        return SaveKnowledgeResponse(
            id=node_id,
            title=req.title,
            category=req.category,
            message=msg,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/tasks", response_model=TaskResponse)
def api_manage_tasks(req: TaskActionRequest):
    try:
        msg = manage_cortex_tasks(
            action=req.action,
            task=req.task,
            task_id=req.task_id,
            status=req.status,
            priority=req.priority,
            due_date=req.due_date,
            project=req.project,
        )
        tasks_list = None
        if req.action in ("list", "status"):
            tasks_list = cortex.list_tasks(
                status=req.status or "pending",
                project=req.project,
            )
        return TaskResponse(
            action=req.action,
            message=msg,
            tasks=tasks_list,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/tasks")
def api_list_tasks(status: str = "pending", project: str = ""):
    try:
        tasks = cortex.list_tasks(status=status, project=project or None)
        return {"status": status, "count": len(tasks), "tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/journal", response_model=JournalResponse)
def api_add_journal(req: JournalRequest):
    try:
        entry_id = cortex.log_journal(
            summary=req.entry,
            sentiment=req.mood,
            key_events=req.tags or "",
        )
        return JournalResponse(
            id=entry_id,
            message=f"Journal entry #{entry_id} logged successfully.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/summary")
def api_get_summary():
    """Returns memory summary formatted for system prompt injection."""
    try:
        tasks = cortex.list_tasks(status="pending", limit=5)
        recent_notes = cortex.get_recent_nodes(limit=5)
        return {
            "pending_tasks": tasks,
            "recent_notes": recent_notes,
        }
    except Exception as e:
        return {"pending_tasks": [], "recent_notes": [], "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    print(f"Starting Cortex Memory Service on {CORTEX_HOST}:{CORTEX_PORT}...")
    uvicorn.run(app, host=CORTEX_HOST, port=CORTEX_PORT)
