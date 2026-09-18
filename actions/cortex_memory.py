"""
Cortex Knowledge & Semantic Memory Actions for D.O.N.N.A.
Exposes tools for semantic memory search, task management, and knowledge journaling.
"""
from typing import Optional, Dict, Any, List
from memory.cortex_engine import cortex


def recall_memory(
    query: str,
    category: Optional[str] = "all",
    limit: int = 5,
) -> str:
    """
    Search Cortex Knowledge Base semantically by meaning.
    Categories: all | notes | projects | identity | preferences | journal | tasks
    """
    query = (query or "").strip()
    if not query:
        return "Укажите поисковый запрос для поиска в памяти Cortex."

    results = cortex.search_nodes(query=query, category=category, limit=limit)
    if not results:
        return f"В памяти Cortex не найдено информации по запросу '{query}'."

    output = [f"🧠 Найдено записей в Cortex по запросу '{query}':\n"]
    for r in results:
        cat_badge = f"[{r['category'].upper()}]"
        tags_str = f" (Теги: {r['tags']})" if r.get("tags") else ""
        score_str = f" [Схожесть: {int(r['score'] * 100)}%]" if "score" in r else ""
        output.append(f"• {cat_badge} **{r['title']}**{tags_str}{score_str}\n  {r['content']}\n")

    return "\n".join(output).strip()


def save_knowledge(
    title: str,
    content: str,
    category: str = "notes",
    tags: str = "",
    importance: int = 3,
) -> str:
    """
    Store or update knowledge in Cortex with semantic vector embeddings.
    category: notes | projects | identity | preferences | ideas | facts | wishes
    """
    title = (title or "").strip()
    content = (content or "").strip()
    if not title and not content:
        return "Необходимо указать заголовок или содержание записи."

    node_id = cortex.store_node(
        title=title or content[:40],
        content=content,
        category=str(category or "notes").lower().strip() or "notes",
        tags=str(tags or "").strip(),
        importance=max(1, min(5, int(importance or 3))),
    )
    return f"Запись сохранена в Cortex [ID #{node_id}, Категория: {category}]: '{title}'."


def manage_cortex_tasks(
    action: str = "list",
    task: Optional[str] = None,
    task_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: str = "normal",
    due_date: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """
    Manage tasks, to-dos, deadlines, and project action items.
    action: add | list | complete | update | delete
    """
    action = (action or "list").lower().strip()

    if action == "add":
        if not task:
            return "Укажите текст задачи (параметр 'task')."
        tid = cortex.create_task(
            task=task,
            project=project or "",
            priority=priority or "normal",
            due_date=due_date or "",
        )
        proj_str = f" (Проект: {project})" if project else ""
        due_str = f" [Срок: {due_date}]" if due_date else ""
        return f"Задача #{tid} успешно создана: '{task}'{proj_str}{due_str} [{priority}]."

    elif action == "list":
        status_filter = status if status else "pending"
        tasks = cortex.list_tasks(status=status_filter, project=project)
        if not tasks:
            proj_str = f" по проекту '{project}'" if project else ""
            return f"Нет активных задач со статусом '{status_filter}'{proj_str}."

        output = [f"📋 Список задач [{status_filter.upper()}]:\n"]
        for t in tasks:
            status_icon = "✅" if t['status'] == 'completed' else "⏳"
            p_badge = f"[{t['priority'].upper()}]" if t['priority'] != 'normal' else ""
            proj = f" (Проект: {t['project']})" if t['project'] else ""
            due = f" [Срок: {t['due_date']}]" if t['due_date'] else ""
            output.append(f"  {status_icon} #{t['id']}: {t['task']}{proj}{due} {p_badge}".strip())
        return "\n".join(output)

    elif action == "complete":
        if not task_id:
            return "Укажите ID задачи (параметр 'task_id') для завершения."
        ok = cortex.update_task(task_id=task_id, status="completed")
        if ok:
            return f"Задача #{task_id} помечена как выполненная! ✅"
        return f"Задача #{task_id} не найдена."

    elif action == "delete":
        if not task_id:
            return "Укажите ID задачи (параметр 'task_id') для удаления."
        ok = cortex.delete_task(task_id=task_id)
        if ok:
            return f"Задача #{task_id} удалена из Cortex."
        return f"Задача #{task_id} не найдена."

    elif action == "update":
        if not task_id:
            return "Укажите ID задачи для обновления."
        ok = cortex.update_task(
            task_id=task_id,
            status=status,
            task_text=task,
            priority=priority,
            due_date=due_date,
        )
        if ok:
            return f"Задача #{task_id} успешно обновлена."
        return f"Задача #{task_id} не найдена."

    return f"Неизвестное действие: '{action}'. Доступные: add | list | complete | update | delete."


def log_journal(summary: str, key_events: str = "") -> str:
    """Record an episodic diary / journal entry in Cortex."""
    summary = (summary or "").strip()
    if not summary:
        return "Укажите краткое содержание или итог для записи в дневник."

    jid = cortex.log_journal(summary=summary, key_events=key_events or "")
    return f"Запись в дневник Cortex [ID #{jid}] успешно добавлена."
