"""
DONNA — Dialog Watchdog Module

Monitors Windows desktop for newly appeared dialogs/message boxes (class "#32770")
indicating silent application launch failures or OS errors.
"""

import time
from typing import Any, Optional, Set

try:
    import win32gui as _w32gui  # type: ignore
    import win32con as _w32con  # type: ignore
    win32gui: Any = _w32gui
    win32con: Any = _w32con
    _PYWIN32_AVAILABLE = True
except ImportError:
    win32gui: Any = None
    win32con: Any = None
    _PYWIN32_AVAILABLE = False


def snapshot_windows() -> Set[int]:
    """
    Take a snapshot of current top-level window handles before launching a process.
    Enumerates windows across both the current thread desktop and the interactive
    input desktop. Returns an empty set if pywin32 is not available or upon error.
    """
    if not _PYWIN32_AVAILABLE or win32gui is None:
        return set()
    hwnds: Set[int] = set()

    def enum_cb(hwnd, _):
        hwnds.add(hwnd)
        return True

    # 1. Enumerate on current thread desktop
    try:
        win32gui.EnumWindows(enum_cb, None)
    except Exception:
        pass

    # 2. Also enumerate on interactive input desktop if available
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            win32gui.EnumDesktopWindows(hdesk, enum_cb, None)
            user32.CloseDesktop(hdesk)
    except Exception:
        pass

    return hwnds


def _extract_dialog_text(hwnd: int) -> str:
    """
    Extract dialog title and static control text from a window handle.
    Returns '{title}: {body}' or whichever part is non-empty.
    """
    if not _PYWIN32_AVAILABLE or win32gui is None:
        return ""
    try:
        title = win32gui.GetWindowText(hwnd).strip()
    except Exception:
        title = ""

    static_texts = []

    def child_cb(child_hwnd, _):
        try:
            cls = win32gui.GetClassName(child_hwnd)
            txt = win32gui.GetWindowText(child_hwnd).strip()
            if cls == "Static" and txt:
                static_texts.append(txt)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumChildWindows(hwnd, child_cb, None)
    except Exception:
        pass

    body = " ".join(static_texts) if static_texts else ""
    if title and body:
        return f"{title}: {body}"
    return title or body


def watch_for_dialog(
    timeout_sec: float = 2.0,
    poll_interval: float = 0.2,
    auto_dismiss: bool = True,
    before_hwnds: Optional[Set[int]] = None,
) -> Optional[str]:
    """
    Polls top-level windows for up to timeout_sec looking for
    a newly appeared window with class "#32770" (standard Windows MessageBox)
    with non-empty title/text that appeared after before_hwnds was taken.

    Returns the dialog text (title + first static control text), or None if
    nothing appeared. Never raises exceptions.
    """
    if not _PYWIN32_AVAILABLE or win32gui is None or win32con is None:
        return None

    try:
        if before_hwnds is None:
            before_hwnds = snapshot_windows()

        start_time = time.time()
        while (time.time() - start_time) < timeout_sec:
            time.sleep(poll_interval)
            current_hwnds = snapshot_windows()
            new_hwnds = current_hwnds - before_hwnds

            for hwnd in new_hwnds:
                try:
                    cls = win32gui.GetClassName(hwnd)
                    if cls == "#32770":
                        text = _extract_dialog_text(hwnd)
                        if text:
                            if auto_dismiss:
                                try:
                                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                                except Exception:
                                    pass
                            return text
                except Exception:
                    continue

        return None
    except Exception:
        return None
