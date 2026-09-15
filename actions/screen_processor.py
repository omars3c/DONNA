"""
actions/screen_processor.py (Deprecated facade for backward compatibility)

This module has been refactored and split into:
- actions.screen_capture: screen and webcam capture (_capture_screen, _capture_camera)
- actions.vision_session: Gemini Live vision session (VisionSession, screen_process, warmup_session)
"""
from __future__ import annotations

from actions.screen_capture import (
    _capture_screen,
    _capture_camera,
    capture_screen,
    capture_camera,
)
from actions.vision_session import (
    VisionSession,
    _VisionSession,
    _ensure_session,
    screen_process,
    warmup_session,
)

__all__ = [
    "_capture_screen",
    "_capture_camera",
    "capture_screen",
    "capture_camera",
    "VisionSession",
    "_VisionSession",
    "_ensure_session",
    "screen_process",
    "warmup_session",
]

if __name__ == "__main__":
    import time
    print("[TEST] screen_processor.py (Compatibility Facade)")
    print("=" * 52)
    mode = input("angle — screen / camera (default: screen): ").strip().lower() or "screen"
    q    = input("Question (Enter = default): ").strip() or "What do you see? Be brief."

    t0 = time.perf_counter()
    warmup_session()
    print(f"Session ready in {time.perf_counter()-t0:.2f}s\n")

    t1 = time.perf_counter()
    ok = screen_process({"angle": mode, "text": q})
    print(f"Queued in {time.perf_counter()-t1:.3f}s — waiting for audio...")
    time.sleep(10)
    print("Done." if ok else "Failed.")