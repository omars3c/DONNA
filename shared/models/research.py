"""Models for Autonomous Research Agent and Web Services."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class WebSearchRequest(BaseModel):
    query: str
    mode: str = "search"  # search | news | research | price | compare
    items: Optional[List[str]] = None
    aspect: Optional[str] = None


class WebSearchResponse(BaseModel):
    query: str
    mode: str
    result: str


class AgentTaskRequest(BaseModel):
    task: str
    user_instructions: Optional[str] = None


class AgentTaskResponse(BaseModel):
    status: str
    result: str
    file_path: Optional[str] = None


class YouTubeRequest(BaseModel):
    action: str = "play"  # play | summarize | get_info | trending
    query: Optional[str] = None
    url: Optional[str] = None
    save: bool = False
    region: Optional[str] = "RU"
