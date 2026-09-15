"""Memory and Cortex models for serialization across microservices."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class RecallRequest(BaseModel):
    query: str
    category: Optional[str] = "all"
    limit: int = 5


class RecallItem(BaseModel):
    id: Optional[int] = None
    title: str
    content: str
    category: str
    tags: Optional[str] = ""
    score: Optional[float] = None


class RecallResponse(BaseModel):
    query: str
    count: int
    results: List[Dict[str, Any]]
    formatted: str


class SaveKnowledgeRequest(BaseModel):
    title: str = ""
    content: str = ""
    category: str = "notes"
    tags: str = ""
    importance: int = 3


class SaveKnowledgeResponse(BaseModel):
    id: int
    title: str
    category: str
    message: str


class TaskActionRequest(BaseModel):
    action: str = "list"  # add | list | complete | update | delete
    task: Optional[str] = None
    task_id: Optional[int] = None
    status: Optional[str] = None
    priority: str = "normal"
    due_date: Optional[str] = None
    project: Optional[str] = None


class TaskResponse(BaseModel):
    action: str
    message: str
    tasks: Optional[List[Dict[str, Any]]] = None


class JournalRequest(BaseModel):
    entry: str
    mood: str = "neutral"
    tags: Optional[str] = ""


class JournalResponse(BaseModel):
    id: int
    message: str
