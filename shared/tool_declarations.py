"""
Tool Declarations for Gemini Function Calling across DONNA microservices.
"""

TOOL_DECLARATIONS = [
    {
        "name": "screen_process",
        "description": "Captures and analyzes what is currently displayed on the user's screen or camera. Call this when user asks what is on screen or asks to look at their screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
            },
        },
    },
    {
        "name": "open_app",
        "description": (
            "Opens any Windows application, browser, or website. "
            "Pass the raw user-provided name (e.g. 'browser', 'chrome', 'youtube', 'погода в токио'). "
            "IMPORTANT: if the result string starts with 'AMBIGUOUS_BROWSER:', "
            "you MUST speak the clarification question to the user and then call open_app "
            "again with the specific browser name the user chose (e.g. 'chrome', 'opera gx')."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {"type": "STRING", "description": "Application or website name, e.g. 'Calculator', 'Chrome', 'youtube', 'browser'"}
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "web_search",
        "description": "Searches the web for news, facts, prices, and research.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Search query or topic"},
                "mode": {"type": "STRING", "description": "search | news | research | price | compare"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "deep_research_report",
        "description": "Performs deep multi-step autonomous research and synthesizes a professional formatted Word document (.docx) or PDF report, then opens it on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task": {"type": "STRING", "description": "Detailed research topic, questions to investigate, and outline for the document"},
                "user_instructions": {"type": "STRING", "description": "Formatting or styling instructions (optional)"}
            },
            "required": ["task"],
        },
    },
    {
        "name": "agent_task",
        "description": "Executes autonomous multi-step problem solving, coding, executing terminal commands, troubleshooting, or inspecting the system using the autonomous ReAct agent.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task": {"type": "STRING", "description": "Detailed engineering, coding, or troubleshooting task to solve autonomously"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "autonomous_task",
        "description": "Alias for agent_task: Executes autonomous multi-step problem solving, coding, command execution, and system debugging.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task": {"type": "STRING", "description": "Detailed task description to solve autonomously"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "recall_memory",
        "description": "Searches Cortex semantic vector memory for notes, facts, past plans, and tasks.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Question or topic to recall from memory"},
                "category": {"type": "STRING", "description": "all | notes | projects | identity | preferences | tasks"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "save_knowledge",
        "description": "Stores a new note, idea, project fact, or user preference in Cortex memory.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING", "description": "Title of the note or insight"},
                "content": {"type": "STRING", "description": "Content of the knowledge note"},
                "category": {"type": "STRING", "description": "notes | projects | identity | preferences"},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "manage_cortex_tasks",
        "description": "Manages tasks and to-dos: add, list, complete, delete.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "add | list | complete | delete"},
                "task": {"type": "STRING", "description": "Task description"},
                "task_id": {"type": "INTEGER", "description": "Task ID for complete/delete"},
                "priority": {"type": "STRING", "description": "normal | high | critical"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "log_journal",
        "description": "Logs daily thoughts or milestones in the episodic diary.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "entry": {"type": "STRING", "description": "Journal text to record"},
            },
            "required": ["entry"],
        },
    },
    {
        "name": "computer_control",
        "description": "Performs mouse clicks, typing text, scrolling, or pressing keys.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "click | type_text | hotkey | scroll"},
                "text": {"type": "STRING", "description": "Text to type on screen"},
                "keys": {"type": "STRING", "description": "Hotkey keys e.g. 'ctrl+c'"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "computer_settings",
        "description": "Controls volume, brightness, closes applications, puts assistant into standby sleep mode, and toggles system settings.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "volume_set | volume_mute | close_app | sleep_display | sleep | standby"},
                "value": {"type": "STRING", "description": "Value e.g. volume level 50"},
                "app_name": {"type": "STRING", "description": "Application name to close"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "system_status",
        "description": "Returns CPU, RAM, GPU, and hardware metrics from Windows Host Agent.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        },
    },
    {
        "name": "browser_control",
        "description": "Controls web browsers (Chrome, Firefox, Opera, Edge). Supports opening URLs in real user profiles, switching tabs, and cleanly closing browsers.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "open | close | close_all | switch | list_browsers | navigate | new_tab | close_tab"},
                "browser": {"type": "STRING", "description": "Browser name: chrome | firefox | edge | opera"},
                "url": {"type": "STRING", "description": "Website URL to navigate to (optional)"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "reminder",
        "description": "Sets, lists, and cancels alarms, reminders, and scheduled tasks integrated with Windows Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "set | list | cancel | cancel_all"},
                "date": {"type": "STRING", "description": "Date in YYYY-MM-DD format (optional, default today)"},
                "time": {"type": "STRING", "description": "Time in HH:MM format (e.g. 14:30)"},
                "message": {"type": "STRING", "description": "Reminder text description"},
                "query": {"type": "STRING", "description": "Search text or ID to cancel"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "youtube_video",
        "description": "Searches, plays, or fetches transcripts and intelligence from YouTube videos.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | search | info | transcript"},
                "query": {"type": "STRING", "description": "Video topic or search title"},
                "url": {"type": "STRING", "description": "Direct YouTube URL if available"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "openclaw_skill",
        "description": "Executes any of the 51 specialized OpenClaw skills including weather, diagram generation, summarization, PDF extraction, and utilities.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "skill_name": {"type": "STRING", "description": "Name of OpenClaw skill, e.g. weather, diagram-maker, summarize, nano-pdf, spotify-player"},
                "query": {"type": "STRING", "description": "Input prompt or query for the skill"},
            },
            "required": ["skill_name"],
        },
    },
]
