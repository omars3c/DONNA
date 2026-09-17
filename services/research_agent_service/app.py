"""
Research Agent Microservice (Port 8003)
Provides autonomous web research, Playwright scraping, document synthesis, and YouTube analytics.
"""

import sys
import asyncio
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import Request, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from shared.models.research import (
    WebSearchRequest,
    WebSearchResponse,
    AgentTaskRequest,
    AgentTaskResponse,
    YouTubeRequest,
)
from shared.config import RESEARCH_PORT, RESEARCH_HOST, ALLOWED_ORIGINS, verify_internal_token
from actions.web_search import web_search as web_search_action
from actions.agent_task import execute_autonomous_agent
from actions.youtube_video import youtube_video

app = FastAPI(
    title="DONNA Research Agent Service",
    description="Autonomous Web Intelligence, Playwright Worker, and Document Generator",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def verify_token_middleware(request: Request, call_next):
    from shared.config import verify_internal_token
    try:
        await verify_internal_token(request)
    except HTTPException as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await call_next(request)


from shared.error_reporter import install_sentinel
install_sentinel(app, "research_agent_service")


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "research_agent_service",
        "port": RESEARCH_PORT,
    }


@app.post("/v1/research/search", response_model=WebSearchResponse)
def api_web_search(req: WebSearchRequest):
    try:
        params = {
            "query": req.query,
            "mode": req.mode or "search",
            "items": req.items or [],
            "aspect": req.aspect or "general",
        }
        res_text = web_search_action(parameters=params)
        return WebSearchResponse(
            query=req.query,
            mode=req.mode,
            result=res_text,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/research/task", response_model=AgentTaskResponse)
async def api_agent_task(req: AgentTaskRequest):
    try:
        # Run autonomous agent (which may run Playwright and docx synthesis)
        full_task = req.task
        if req.user_instructions:
            full_task = f"{req.task}\nИнструкции: {req.user_instructions}"
        res_text = await asyncio.to_thread(execute_autonomous_agent, full_task)
        return AgentTaskResponse(
            status="completed",
            result=res_text,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/research/youtube")
def api_youtube_video(req: YouTubeRequest):
    try:
        params = {
            "action": req.action,
            "query": req.query,
            "url": req.url,
            "save": req.save,
            "region": req.region or "RU",
        }
        res_text = youtube_video(parameters=params)
        return {"action": req.action, "result": res_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    print(f"Starting Research Agent Service on {RESEARCH_HOST}:{RESEARCH_PORT}...")
    uvicorn.run(app, host=RESEARCH_HOST, port=RESEARCH_PORT)
