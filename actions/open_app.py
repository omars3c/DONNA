import json
import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
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

# Path to machine-specific user preferences (browser default, etc.)
_PREFS_PATH = Path(__file__).resolve().parent.parent / "config" / "user_prefs.json"


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class LaunchResult:
    ok: bool
    confirmed: bool = False
    detail: str = ""


# ── User prefs (local JSON, never raises) ────────────────────────────────────

def _load_user_prefs() -> dict:
    try:
        if _PREFS_PATH.exists():
            return json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_user_prefs(prefs: dict) -> None:
    try:
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PREFS_PATH.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Registry helpers ──────────────────────────────────────────────────────────

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
    """Returns the exe path for the handler of 'http' or 'mailto', via Windows registry."""
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


def _enumerate_installed_browsers() -> list:
    """
    Returns a list of {'name': str, 'path': str} for all installed browsers,
    ordered so that the system default (UserChoice ProgId) is first.

    Sources, in order:
    1. HKLM\\SOFTWARE\\Clients\\StartMenuInternet
    2. shutil.which() + common paths fallback
    """
    browsers: list = []
    seen_paths: set = set()

    # Determine default browser ProgId from registry
    default_prog_id: Optional[str] = None
    try:
        import winreg
        uc_key = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uc_key) as k:
            default_prog_id, _ = winreg.QueryValueEx(k, "ProgId")
    except Exception:
        pass

    # Read installed browsers from registry
    try:
        import winreg
        start_menu_key = r"SOFTWARE\Clients\StartMenuInternet"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, start_menu_key) as base:
            idx = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(base, idx)
                    idx += 1
                    with winreg.OpenKey(base, sub_name) as sub:
                        try:
                            display_name, _ = winreg.QueryValueEx(sub, "")
                        except Exception:
                            display_name = sub_name

                        exe_path: Optional[str] = None
                        try:
                            with winreg.OpenKey(sub, r"shell\open\command") as cmd_k:
                                cmd_str, _ = winreg.QueryValueEx(cmd_k, "")
                                exe_path = _extract_exe_from_command(cmd_str)
                        except Exception:
                            pass

                        if exe_path and os.path.isfile(exe_path):
                            norm_path = os.path.normcase(exe_path)
                            if norm_path not in seen_paths:
                                seen_paths.add(norm_path)
                                # Check if this is the system default (match by exe name in ProgId)
                                is_default = bool(
                                    default_prog_id and
                                    os.path.basename(exe_path).lower().replace(".exe", "") in default_prog_id.lower()
                                )
                                entry = {"name": display_name, "path": exe_path, "_default": is_default}
                                if is_default:
                                    browsers.insert(0, entry)
                                else:
                                    browsers.append(entry)
                except OSError:
                    break
    except Exception:
        pass

    # Fallback: shutil.which + common paths
    _localappdata = os.environ.get("LOCALAPPDATA", "")
    _prog_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    _prog_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")

    _fallback_browsers = [
        ("Google Chrome", [
            shutil.which("chrome"),
            shutil.which("chrome.exe"),
            os.path.join(_prog_files, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(_prog_files_x86, r"Google\Chrome\Application\chrome.exe"),
        ]),
        ("Mozilla Firefox", [
            shutil.which("firefox"),
            shutil.which("firefox.exe"),
            os.path.join(_prog_files, r"Mozilla Firefox\firefox.exe"),
            os.path.join(_prog_files_x86, r"Mozilla Firefox\firefox.exe"),
        ]),
        ("Opera GX", [
            os.path.join(_localappdata, r"Programs\Opera GX\opera.exe"),
        ]),
        ("Opera", [
            os.path.join(_localappdata, r"Programs\Opera\opera.exe"),
            shutil.which("opera"),
        ]),
        ("Microsoft Edge", [
            shutil.which("msedge"),
            shutil.which("msedge.exe"),
            os.path.join(_prog_files, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(_prog_files_x86, r"Microsoft\Edge\Application\msedge.exe"),
        ]),
        ("Brave Browser", [
            os.path.join(_prog_files, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.join(_prog_files_x86, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        ]),
    ]

    for friendly_name, paths in _fallback_browsers:
        for p in paths:
            if p and os.path.isfile(p):
                norm_path = os.path.normcase(p)
                if norm_path not in seen_paths:
                    seen_paths.add(norm_path)
                    browsers.append({"name": friendly_name, "path": p, "_default": False})
                break

    # Strip the internal _default marker
    return [{"name": b["name"], "path": b["path"]} for b in browsers]


def _get_default_browser_path() -> Optional[str]:
    """
    Returns the exe path of the system default browser (http handler), or None.
    Tries UserChoice registry first, then falls back to _enumerate_installed_browsers()[0].
    """
    # 1. Try registry UserChoice → direct exe
    exe = _get_protocol_handler_exe("http")
    if exe and os.path.isfile(exe):
        return exe

    # 2. Fall back to first enumerated browser
    browsers = _enumerate_installed_browsers()
    if browsers:
        return browsers[0]["path"]
    return None


# ── Normalizer ────────────────────────────────────────────────────────────────

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


# ── Confirmed-launch helper ───────────────────────────────────────────────────

def _proc_is_alive(proc: subprocess.Popen, wait_sec: float = 0.7) -> bool:
    """
    Wait `wait_sec` seconds then check if the process is still running.
    Uses psutil if available for a more reliable check, otherwise proc.poll().
    """
    time.sleep(wait_sec)
    if _PSUTIL:
        try:
            return psutil.pid_exists(proc.pid) and psutil.Process(proc.pid).is_running()
        except Exception:
            pass
    return proc.poll() is None


# ── Browser-name fuzzy matching ───────────────────────────────────────────────

_BROWSER_ALIASES: dict = {
    # Chrome
    "chrome": "google chrome",
    "google chrome": "google chrome",
    "хром": "google chrome",
    "гугл хром": "google chrome",
    # Firefox
    "firefox": "mozilla firefox",
    "firefox browser": "mozilla firefox",
    "mozilla firefox": "mozilla firefox",
    "фаерфокс": "mozilla firefox",
    "файрфокс": "mozilla firefox",
    # Opera GX
    "opera gx": "opera gx",
    "operagx": "opera gx",
    "опера гх": "opera gx",
    "opera": "opera",
    "опера": "opera",
    # Edge
    "edge": "microsoft edge",
    "microsoft edge": "microsoft edge",
    "msedge": "microsoft edge",
    "эдж": "microsoft edge",
    # Brave
    "brave": "brave browser",
    "brave browser": "brave browser",
    "брейв": "brave browser",
    "брав": "brave browser",
}


def _match_browser(name: str, browsers: list) -> Optional[dict]:
    """
    Fuzzy-match a user-supplied name (already transliterated) to a browser in
    the provided list.  Returns the matching browser dict or None.
    """
    name_lower = name.strip().lower()
    # Normalize via alias table
    canonical = _BROWSER_ALIASES.get(name_lower)

    for b in browsers:
        b_name_lower = b["name"].lower()
        b_exe_lower = os.path.basename(b["path"]).lower().replace(".exe", "")

        if canonical:
            if canonical in b_name_lower or b_name_lower in canonical:
                return b
        # Direct substring match
        if name_lower in b_name_lower or b_name_lower in name_lower:
            return b
        # Exe-name match (e.g. "opera" matches "opera.exe")
        if name_lower in b_exe_lower or b_exe_lower in name_lower:
            return b

    return None


# ── Generic category resolver ─────────────────────────────────────────────────

_BROWSER_TERMS = {
    "browser", "браузер", "brauzer", "брузер",
    "internet", "web browser", "интернет",
}
_EMAIL_TERMS = {"email", "mail", "почта", "pochta", "pocta"}
_EXPLORER_TERMS = {"explorer", "file manager", "filemanager", "проводник", "provodnik"}


def _resolve_generic_category(name: str, save_as_default_if_disambiguation: bool = False) -> Optional[str]:
    """
    Resolves generic categories (browser, email, explorer) to an exe path.

    Returns:
      - Executable path string on success.
      - "AMBIGUOUS_BROWSER:<name1>,<name2>,..." when multiple browsers are installed
        and no saved default exists (caller must ask user to clarify).
      - None if category not recognised or resolution failed completely.
    """
    if _SYSTEM != "Windows":
        return None

    raw = name.strip().lower()
    norm = _normalize(name).strip().lower()

    # ── Browser ──
    if raw in _BROWSER_TERMS or norm in _BROWSER_TERMS:
        prefs = _load_user_prefs()
        saved = prefs.get("default_browser")
        if saved and isinstance(saved, dict) and os.path.isfile(saved.get("path", "")):
            print(f"[open_app] Using saved default browser: {saved['name']} ({saved['path']})")
            return saved["path"]

        browsers = _enumerate_installed_browsers()
        if not browsers:
            return None  # No browser installed at all

        if len(browsers) == 1:
            return browsers[0]["path"]

        # Multiple browsers — return AMBIGUOUS sentinel
        names = ", ".join(b["name"] for b in browsers)
        return f"AMBIGUOUS_BROWSER:{names}"

    # ── Email ──
    if raw in _EMAIL_TERMS or norm in _EMAIL_TERMS:
        exe = _get_protocol_handler_exe("mailto")
        if exe:
            return exe

    # ── File Explorer ──
    if raw in _EXPLORER_TERMS or norm in _EXPLORER_TERMS:
        return "explorer.exe"

    return None


# ── Common Windows application aliases & Registry / Start Menu lookup ────────
_WINDOWS_APP_ALIASES = {
    "calc": "calc.exe",
    "calculator": "calc.exe",
    "калькулятор": "calc.exe",
    "notepad": "notepad.exe",
    "блокнот": "notepad.exe",
    "paint": "mspaint.exe",
    "mspaint": "mspaint.exe",
    "пейнт": "mspaint.exe",
    "word": "winword.exe",
    "ворд": "winword.exe",
    "excel": "excel.exe",
    "эксель": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "пауэрпоинт": "powerpnt.exe",
    "cmd": "cmd.exe",
    "командная строка": "cmd.exe",
    "powershell": "powershell.exe",
    "павершелл": "powershell.exe",
    "task manager": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "диспетчер задач": "taskmgr.exe",
    "control": "control.exe",
    "control panel": "control.exe",
    "панель управления": "control.exe",
    "settings": "ms-settings:",
    "параметры": "ms-settings:",
    "настройки": "ms-settings:",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "терминал": "wt.exe",
    "snipping tool": "snippingtool.exe",
    "ножницы": "snippingtool.exe",
    "regedit": "regedit.exe",
    "реестр": "regedit.exe",
    "telegram": "telegram.exe",
    "телеграм": "telegram.exe",
    "телега": "telegram.exe",
    "discord": "discord.exe",
    "дискорд": "discord.exe",
    "spotify": "spotify.exe",
    "спотифай": "spotify.exe",
    "steam": "steam.exe",
    "стим": "steam.exe",
}


def _find_app_in_registry_app_paths(name: str) -> Optional[str]:
    """Search Windows Registry App Paths for registered exe paths."""
    if _SYSTEM != "Windows":
        return None
    try:
        import winreg
        candidates = [name, f"{name}.exe"]
        for root_key in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            base_path = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
            for cand in candidates:
                try:
                    with winreg.OpenKey(root_key, rf"{base_path}\{cand}") as k:
                        val, _ = winreg.QueryValueEx(k, "")
                        if val and os.path.isfile(val):
                            return val
                except OSError:
                    pass
            try:
                with winreg.OpenKey(root_key, base_path) as base:
                    idx = 0
                    while True:
                        try:
                            sub_name = winreg.EnumKey(base, idx)
                            idx += 1
                            stem = sub_name.lower().removesuffix(".exe")
                            if stem == name.lower():
                                with winreg.OpenKey(base, sub_name) as sub:
                                    val, _ = winreg.QueryValueEx(sub, "")
                                    if val and os.path.isfile(val):
                                        return val
                        except OSError:
                            break
            except OSError:
                pass
    except Exception:
        pass
    return None


def _find_app_in_start_menu(name: str) -> Optional[str]:
    """Search Windows Start Menu for matching .lnk shortcut files."""
    if _SYSTEM != "Windows":
        return None
    search_dirs = [
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
    ]
    name_clean = name.strip().lower()
    for sdir in search_dirs:
        if not os.path.isdir(sdir):
            continue
        try:
            for root, dirs, files in os.walk(sdir):
                # Don't descend more than 3 levels
                rel = os.path.relpath(root, sdir)
                if rel.count(os.sep) > 3:
                    dirs.clear()
                    continue
                for f in files:
                    f_lower = f.lower()
                    if f_lower.endswith(".lnk"):
                        f_stem = f_lower[:-4]
                        if f_stem == name_clean or name_clean in f_stem or f_stem in name_clean:
                            full_path = os.path.join(root, f)
                            if os.path.exists(full_path):
                                return full_path
        except Exception:
            continue
    return None


def _is_web_url(target: str) -> bool:
    """Check if target string is a web URL."""
    t = target.strip().lower()
    if t.startswith(("http://", "https://", "www.")):
        return True
    tld_pattern = r'^[a-z0-9-]+(\.[a-z0-9-]+)*\.(com|org|net|io|ru|dev|app|ai|co|info|me)(/.*)?$'
    return bool(re.match(tld_pattern, t))


# ── Windows launcher ──────────────────────────────────────────────────────────

def _launch_windows(app_name: str) -> LaunchResult:
    """
    Hierarchical non-blocking Windows launcher.

    Steps:
    1. Generic category resolution (browser/email/explorer)
    2. Web URL routing (only if target is an actual URL)
    3. Common Windows aliases and URI protocols
    4. Direct binary lookup via PATH / which
    5. Registry App Paths lookup
    6. Start Menu shortcuts lookup (.lnk)
    7. Safe protocol / file invocation
    """
    # 1. Generic category resolution
    cat_result = _resolve_generic_category(app_name)
    if cat_result is not None:
        if cat_result.startswith("AMBIGUOUS_BROWSER:"):
            # Surface to caller immediately — do not launch
            return LaunchResult(ok=False, confirmed=False, detail=cat_result)

        try:
            proc = subprocess.Popen([cat_result], shell=False)
            if _proc_is_alive(proc):
                return LaunchResult(ok=True, confirmed=True, detail=f"Category launched: {cat_result}")
            return LaunchResult(ok=False, confirmed=False, detail=f"Category process died immediately: {cat_result}")
        except Exception:
            if hasattr(os, "startfile"):
                try:
                    os.startfile(cat_result)
                    return LaunchResult(ok=True, confirmed=True, detail=f"startfile: {cat_result}")
                except Exception:
                    pass
            return LaunchResult(ok=False, confirmed=False, detail=f"Category launch failed: {cat_result}")

    # 2. Web URL routing
    if _is_web_url(app_name):
        url = app_name if app_name.startswith(("http://", "https://")) else f"https://{app_name}"
        browser_path = _get_default_browser_path()
        if browser_path:
            try:
                proc = subprocess.Popen([browser_path, url], shell=False)
                if _proc_is_alive(proc, wait_sec=0.8):
                    return LaunchResult(ok=True, confirmed=True, detail=f"Browser URL opened: {browser_path} '{url}'")
                return LaunchResult(ok=True, confirmed=True, detail=f"Browser URL opened (delegated): {browser_path} '{url}'")
            except Exception:
                pass
        if hasattr(os, "startfile"):
            try:
                os.startfile(url)
                return LaunchResult(ok=True, confirmed=True, detail=f"startfile URL: {url}")
            except Exception:
                pass

    # 3. Known application aliases
    target_cmd = _WINDOWS_APP_ALIASES.get(app_name.lower()) or _WINDOWS_APP_ALIASES.get(_normalize(app_name).lower())
    if target_cmd:
        if target_cmd.endswith(":") or not target_cmd.endswith(".exe"):
            if hasattr(os, "startfile"):
                try:
                    os.startfile(target_cmd)
                    return LaunchResult(ok=True, confirmed=True, detail=f"URI protocol launched: {target_cmd}")
                except Exception:
                    pass
        target_path = shutil.which(target_cmd) or _find_app_in_registry_app_paths(target_cmd) or _find_app_in_start_menu(target_cmd)
        if target_path:
            try:
                if target_path.lower().endswith(".lnk") and hasattr(os, "startfile"):
                    os.startfile(target_path)
                    return LaunchResult(ok=True, confirmed=True, detail=f"Shortcut launched: {target_path}")
                proc = subprocess.Popen([target_path], shell=False)
                if _proc_is_alive(proc):
                    return LaunchResult(ok=True, confirmed=True, detail=f"Alias launched: {target_path}")
                return LaunchResult(ok=True, confirmed=True, detail=f"Alias launched (delegated): {target_path}")
            except Exception:
                pass

    # 4. Direct binary lookup via PATH / which
    binary = shutil.which(app_name) or shutil.which(f"{app_name}.exe") or shutil.which(app_name.split(".")[0])
    target = binary or (app_name if os.path.isfile(app_name) else None)
    if target:
        try:
            proc = subprocess.Popen([target], shell=False)
            if _proc_is_alive(proc):
                return LaunchResult(ok=True, confirmed=True, detail=f"Binary launched: {target}")
            return LaunchResult(ok=True, confirmed=True, detail=f"Binary launched (delegated): {target}")
        except Exception:
            pass

    # 5. Registry App Paths lookup
    reg_path = _find_app_in_registry_app_paths(app_name) or _find_app_in_registry_app_paths(_normalize(app_name))
    if reg_path:
        try:
            proc = subprocess.Popen([reg_path], shell=False)
            if _proc_is_alive(proc):
                return LaunchResult(ok=True, confirmed=True, detail=f"Registry App Path launched: {reg_path}")
            return LaunchResult(ok=True, confirmed=True, detail=f"Registry App Path launched (delegated): {reg_path}")
        except Exception:
            pass

    # 6. Start Menu / Programs shortcuts (.lnk) lookup
    lnk_path = _find_app_in_start_menu(app_name) or _find_app_in_start_menu(_normalize(app_name))
    if lnk_path and hasattr(os, "startfile"):
        try:
            os.startfile(lnk_path)
            return LaunchResult(ok=True, confirmed=True, detail=f"Start Menu shortcut launched: {lnk_path}")
        except Exception:
            pass

    # 7. Safe OS startfile invocation as last resort
    if hasattr(os, "startfile") and (":" in app_name or os.path.exists(app_name)):
        try:
            os.startfile(app_name)
            return LaunchResult(ok=True, confirmed=False, detail=f"os.startfile invoked for {app_name}")
        except Exception as e:
            return LaunchResult(ok=False, confirmed=False, detail=str(e))

    return LaunchResult(ok=False, confirmed=False, detail=f"Failed to launch {app_name}")


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
        escaped_name = app_name.replace("'", "\\'")
        query = f"kMDItemContentType == 'com.apple.application-bundle' && (kMDItemFSName == '{escaped_name}.app'c || kMDItemDisplayName == '{escaped_name}'c)"
        r = subprocess.run(["mdfind", query], capture_output=True, text=True, timeout=5)
        paths = [p for p in r.stdout.splitlines() if p.strip()]
        if paths:
            res = subprocess.run(["open", paths[0].strip()], capture_output=True, timeout=8)
            if res.returncode == 0:
                time.sleep(0.5)
                return True
    except Exception:
        pass

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
    **kwargs,
) -> str:
    if isinstance(parameters, str):
        parameters_str = parameters.strip()
        if parameters_str.startswith("{") and parameters_str.endswith("}"):
            try:
                parsed = json.loads(parameters_str)
                params = parsed if isinstance(parsed, dict) else {"app_name": parameters_str}
            except Exception:
                params = {"app_name": parameters_str}
        else:
            params = {"app_name": parameters_str}
    elif isinstance(parameters, dict):
        params = dict(parameters)
    else:
        params = {}

    for k, v in kwargs.items():
        if k not in params or params[k] is None:
            params[k] = v

    raw_name = params.get("app_name") or params.get("name") or params.get("app")
    app_name = str(raw_name).strip() if raw_name is not None else ""
    # Whether the previous call returned AMBIGUOUS_BROWSER and the user has now
    # chosen a specific browser (so we should save it as the default).
    pending_disambiguation: bool = bool(params.get("pending_disambiguation", False))

    if not app_name:
        return "No application name provided."

    launcher = _OS_LAUNCHERS.get(_SYSTEM)
    if launcher is None:
        return f"Unsupported operating system: {_SYSTEM}"

    normalized = _normalize(app_name)
    print(f"[open_app] Launching: '{app_name}' -> '{normalized}' ({_SYSTEM}) pending_disambiguation={pending_disambiguation}")

    if player:
        player.write_log(f"[open_app] {app_name}")

    try:
        # ── Check: is app_name a specific browser chosen after AMBIGUOUS_BROWSER? ──
        if pending_disambiguation and _SYSTEM == "Windows":
            browsers = _enumerate_installed_browsers()
            # Try to match with normalized name (transliterated)
            matched = _match_browser(normalized, browsers) or _match_browser(app_name.lower(), browsers)
            if matched:
                print(f"[open_app] Disambiguation: user chose '{matched['name']}' ({matched['path']})")
                try:
                    proc = subprocess.Popen([matched["path"]], shell=False)
                    alive = _proc_is_alive(proc)
                    if alive:
                        # Save as default
                        prefs = _load_user_prefs()
                        prefs["default_browser"] = {"name": matched["name"], "path": matched["path"]}
                        _save_user_prefs(prefs)
                        print(f"[open_app] Saved default browser: {matched['name']}")
                        return f"Opened {matched['name']}."
                except Exception as e:
                    pass  # Fall through to normal resolution below

        # Snapshot windows before launch attempt
        before_hwnds = snapshot_windows()

        result = _invoke_launcher(launcher, normalized)
        if not result.ok and normalized.lower() != app_name.lower():
            result = _invoke_launcher(launcher, app_name)

        # ── AMBIGUOUS_BROWSER: surface to caller without launching ──
        if not result.ok and result.detail.startswith("AMBIGUOUS_BROWSER:"):
            browser_names = result.detail.removeprefix("AMBIGUOUS_BROWSER:").strip()
            return (
                f"AMBIGUOUS_BROWSER: несколько браузеров найдено — {browser_names}. "
                f"Спроси пользователя, какой открыть, и вызови open_app снова с его выбором."
            )

        if result.ok and result.confirmed:
            return f"Opened {app_name}."

        if result.ok and not result.confirmed:
            # Fallback launch was used: check for newly spawned error dialog
            dialog_text = watch_for_dialog(timeout_sec=2.0, before_hwnds=before_hwnds)
            if dialog_text:
                report(
                    severity="INFO",
                    source="open_app",
                    message=f"App not found: {app_name}, native dialog detected",
                    context={"app_name": app_name, "normalized": normalized, "dialog": dialog_text},
                )
                return f"Не удалось найти {app_name} на компьютере."

            report(
                severity="INFO",
                source="open_app",
                message=f"Unconfirmed launch: {app_name}",
                context={"app_name": app_name, "normalized": normalized},
            )
            return f"Started a launch attempt for {app_name}, but could not confirm it opened."

        # Total failure: nothing succeeded (app is not installed or not found)
        err_detail = result.detail or "Could not find application"
        report(
            severity="INFO",
            source="open_app",
            message=f"App not found or failed to launch: {app_name} ({err_detail})",
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
            message=f"Error executing open_app for {app_name}: {e}",
            exc=e,
            context={"app_name": app_name, "normalized": normalized},
        )
        return f"Failed to open {app_name}: {e}"


