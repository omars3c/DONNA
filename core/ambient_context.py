"""
Ambient Context Engine for D.O.N.N.A. / J.A.R.V.I.S.
Provides zero-friction awareness of the user's active engineering environment:
- Active foreground window title and process (VS Code, Windows Terminal, Browser, etc.)
- Recent text/code snippet in clipboard (if text < 3000 chars)
Allows the assistant to know what file or error the user is looking at without requiring manual screenshots.
"""

from __future__ import annotations

import sys
import ctypes
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("AmbientContext")

_user32 = None
_kernel32 = None
if sys.platform == "win32":
    try:
        _user32 = ctypes.windll.user32
        _kernel32 = ctypes.windll.kernel32
    except Exception as e:
        logger.warning(f"[Ambient] Win32 DLL load failed: {e}")


def get_active_window_info() -> Dict[str, str]:
    """Returns title and process name of the active foreground window."""
    if not _user32:
        return {"title": "", "process": ""}

    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return {"title": "", "process": ""}

        buf = ctypes.create_unicode_buffer(512)
        _user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.strip()

        pid = ctypes.c_ulong()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        process_name = ""
        if pid.value:
            try:
                import psutil
                p = psutil.Process(pid.value)
                process_name = p.name()
            except Exception:
                pass

        return {"title": title, "process": process_name}
    except Exception as e:
        logger.debug(f"[Ambient] Failed to get foreground window: {e}")
        return {"title": "", "process": ""}


def get_clipboard_snippet(max_length: int = 2000) -> Optional[str]:
    """Safely retrieves text snippet from clipboard if valid."""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        content = root.clipboard_get()
        root.destroy()

        if content and isinstance(content, str):
            clean = content.strip()
            if 3 <= len(clean) <= max_length:
                return clean
    except Exception:
        pass
    return None


def get_ambient_context() -> Dict[str, Any]:
    win = get_active_window_info()
    clip = get_clipboard_snippet()
    return {
        "window_title": win.get("title", ""),
        "process_name": win.get("process", ""),
        "clipboard": clip or "",
    }


def format_ambient_for_prompt() -> str:
    ctx = get_ambient_context()
    lines = []
    win_title = ctx.get("window_title")
    proc = ctx.get("process_name")
    clip = ctx.get("clipboard")

    if win_title or proc:
        proc_str = f" ({proc})" if proc else ""
        lines.append(f"- Active Window: {win_title}{proc_str}")

    if clip:
        # One-line or short indented snippet
        snippet = clip[:400].replace("\r\n", " ").replace("\n", " ")
        lines.append(f"- Clipboard Preview: {snippet}")

    if lines:
        return (
            "[AMBIENT WORKSPACE CONTEXT]\n"
            + "\n".join(lines) + "\n"
            f"(The user is actively interacting with this window/content. "
            f"Use this context naturally without explicitly asking what they are working on.)\n\n"
        )
    return ""
