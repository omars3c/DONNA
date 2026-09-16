import os
import time
import subprocess
import platform
import shutil

import re
from dataclasses import dataclass
from typing import Optional

try:
    from shared.error_reporter import report
except Exception:
    def report(*args, **kwargs):
        pass

from actions.dialog_watchdog import watch_for_dialog, snapshot_windows

try:
    import psutil  # type: ignore
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

_SYSTEM = platform.system()


@dataclass
class LaunchResult:
    ok: bool
    confirmed: bool = False
    detail: str = ""


def _extract_exe_from_command(cmd_str: str) -> Optional[str]:
    if not cmd_str:
        return None
    cmd_str = cmd_str.strip()
    if cmd_str.startswith('"'):
        end = cmd_str.find('"', 1)
        if end != -1:
            exe = cmd_str[1:end].strip()
            if exe:
                return exe
    match = re.search(r'([a-zA-Z]:\\[^"]+?\.exe)', cmd_str, re.IGNORECASE)
    if match:
        return match.group(1)
    parts = cmd_str.split()
    return parts[0] if parts else None


def _get_protocol_handler_exe(protocol: str) -> Optional[str]:
    try:
        import winreg
        key_path = rf"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{protocol}\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            prog_id, _ = winreg.QueryValueEx(k, "ProgId")
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command") as k:
            cmd_str, _ = winreg.QueryValueEx(k, "")
        return _extract_exe_from_command(cmd_str)
    except Exception:
        return None


def _normalize(raw: str) -> str:
    """Dynamic cross-language normalizer without static dictionaries."""
    key = raw.strip()
    # If already Latin or file path, return as is
    if all(ord(c) < 128 for c in key):
        return key

    # Transliteration for cross-language matching (e.g. 'хром' -> 'chrome', 'блокнот' -> 'notepad')
    _trans_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    return "".join(_trans_map.get(c, c) for c in key.lower())


def _resolve_generic_category(name: str) -> Optional[str]:
    """
    Resolves generic categories (browser, email, explorer) via Windows Registry or OS constants.
    Returns executable path or None. Does not affect specific application names.
    """
    if _SYSTEM != "Windows":
        return None

    raw = name.strip().lower()
    norm = _normalize(name).strip().lower()

    # Browser
    browser_terms = {"browser", "браузер", "brauzer"}
    if raw in browser_terms or norm in browser_terms:
        exe = _get_protocol_handler_exe("http")
        if exe:
            return exe

    # Email
    email_terms = {"email", "mail", "почта", "pochta", "pocta"}
    if raw in email_terms or norm in email_terms:
        exe = _get_protocol_handler_exe("mailto")
        if exe:
            return exe

    # Explorer / File manager
    explorer_terms = {"explorer", "file manager", "filemanager", "проводник", "provodnik"}
    if raw in explorer_terms or norm in explorer_terms:
        return "explorer.exe"

    return None


def _launch_windows(app_name: str) -> LaunchResult:
    """
    Hierarchical non-blocking Windows launcher:
    1. Generic category resolution -> os.startfile / Popen (confirmed=True)
    2. Direct binary lookup -> Popen([binary]) (confirmed=True)
    3. Blind shell start -> cmd start (confirmed=False)
    """
    # 1. Generic category resolution
    cat_path = _resolve_generic_category(app_name)
    if cat_path:
        if hasattr(os, "startfile"):
            try:
                os.startfile(cat_path)
                return LaunchResult(ok=True, confirmed=True, detail=f"Category resolved to {cat_path}")
            except Exception:
                pass
        try:
            subprocess.Popen([cat_path])
            return LaunchResult(ok=True, confirmed=True, detail=f"Category Popen launched {cat_path}")
        except Exception:
            pass

    # 2. Direct binary lookup
    binary = shutil.which(app_name) or shutil.which(app_name.split(".")[0])
    target = binary or (app_name if os.path.isfile(app_name) else None)
    if target:
        try:
            subprocess.Popen([target])
            return LaunchResult(ok=True, confirmed=True, detail=f"Binary launched: {target}")
        except Exception:
            pass

    # 3. Fallback: blind shell start (unconfirmed)
    try:
        subprocess.Popen(f'start "" "{app_name}"', shell=True)
        return LaunchResult(ok=True, confirmed=False, detail=f"Shell start invoked for {app_name}")
    except Exception as e:
        return LaunchResult(ok=False, confirmed=False, detail=str(e))


def _launch_macos(app_name: str) -> bool:

    try:
        result = subprocess.run(
            ["open", "-a", app_name],
            capture_output=True, timeout=8
        )
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["open", "-a", f"{app_name}.app"],
            capture_output=True, timeout=8
        )
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    binary = shutil.which(app_name) or shutil.which(app_name.lower())
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        import pyautogui  # type: ignore
        pyautogui.hotkey("command", "space")
        time.sleep(0.6)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"[open_app] Spotlight failed: {e}")

    return False


_LINUX_TERMINAL_FALLBACKS = [
    "x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal",
    "xterm", "lxterminal", "mate-terminal", "tilix", "alacritty", "kitty",
]

def _launch_linux(app_name: str) -> bool:

    # terminal emulators: try common ones in order
    if app_name in ("x-terminal-emulator", "gnome-terminal", "terminal"):
        for term in _LINUX_TERMINAL_FALLBACKS:
            if shutil.which(term):
                try:
                    subprocess.Popen([term], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(1.0)
                    return True
                except Exception:
                    continue

    binary = (
        shutil.which(app_name) or
        shutil.which(app_name.lower()) or
        shutil.which(app_name.lower().replace(" ", "-")) or
        shutil.which(app_name.lower().replace(" ", "_"))
    )
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        subprocess.run(
            ["xdg-open", app_name],
            capture_output=True, timeout=5
        )
        return True
    except Exception:
        pass

    for desktop_name in [
        app_name.lower(),
        app_name.lower().replace(" ", "-"),
        app_name.lower().replace(" ", ""),
    ]:
        try:
            result = subprocess.run(
                ["gtk-launch", desktop_name],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass

    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
    "Darwin":  _launch_macos,
    "Linux":   _launch_linux,
}

def _invoke_launcher(launcher, target: str) -> LaunchResult:
    res = launcher(target)
    if isinstance(res, LaunchResult):
        return res
    if bool(res):
        return LaunchResult(ok=True, confirmed=True, detail=f"Launched {target}")
    return LaunchResult(ok=False, confirmed=False, detail=f"Failed to launch {target}")


def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    app_name = (parameters or {}).get("app_name", "").strip()

    if not app_name:
        return "No application name provided."

    launcher = _OS_LAUNCHERS.get(_SYSTEM)
    if launcher is None:
        return f"Unsupported operating system: {_SYSTEM}"

    normalized = _normalize(app_name)
    print(f"[open_app] Launching: '{app_name}' -> '{normalized}' ({_SYSTEM})")

    if player:
        player.write_log(f"[open_app] {app_name}")

    try:
        # Snapshot windows before launch attempt
        before_hwnds = snapshot_windows()

        result = _invoke_launcher(launcher, normalized)
        if not result.ok and normalized.lower() != app_name.lower():
            result = _invoke_launcher(launcher, app_name)

        if result.ok and result.confirmed:
            return f"Opened {app_name}."

        if result.ok and not result.confirmed:
            # Fallback blind launch (step 3) was used: check for newly spawned error dialog
            dialog_text = watch_for_dialog(timeout_sec=2.0, before_hwnds=before_hwnds)
            if dialog_text:
                report(
                    severity="ERROR",
                    source="open_app_dialog_detect",
                    message=dialog_text,
                    context={"app_name": app_name, "normalized": normalized},
                )
                return f"Failed to open {app_name}: {dialog_text}"

            report(
                severity="WARNING",
                source="open_app",
                message=f"Unconfirmed launch: {app_name}",
                context={"app_name": app_name, "normalized": normalized},
            )
            return f"Started a launch attempt for {app_name}, but could not confirm it opened."

        # Total failure: nothing succeeded
        err_detail = result.detail or "Could not confirm that application launched"
        report(
            severity="ERROR",
            source="open_app",
            message=f"Failed to open {app_name}: {err_detail}",
            context={"app_name": app_name, "normalized": normalized},
        )
        return (
            f"Could not confirm that {app_name} launched. "
            f"It may still be loading, or it might not be installed."
        )
    except Exception as e:
        print(f"[open_app] Error: {e}")
        report(
            severity="ERROR",
            source="open_app",
            message=f"Failed to open {app_name}: {e}",
            context={"app_name": app_name, "normalized": normalized},
        )
        return f"Failed to open {app_name}: {e}"