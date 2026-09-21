"""
D.O.N.N.A. / J.A.R.V.I.S. Setup & Dependency Installer
Supports modern high-speed uv package manager with automatic pip fallback.
"""
import subprocess
import sys
import platform
import shutil
from pathlib import Path

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
REQ_PATH = BASE_DIR / "requirements.txt"
UV_PATH = shutil.which("uv")

if UV_PATH:
    print("[D.O.N.N.A. Setup] High-speed 'uv' detected! Syncing isolated environment via 'uv sync'...")
    subprocess.run(["uv", "sync"], check=True, cwd=str(BASE_DIR))

    print("[D.O.N.N.A. Setup] Installing Playwright browsers via uv...")
    subprocess.run(["uv", "run", "playwright", "install"], check=True, cwd=str(BASE_DIR))
else:
    print("[INFO] TIP: Install 'uv' for 10x-100x faster deterministic setup:")
    print("      powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\"\n")
    print("[D.O.N.N.A. Setup] Falling back to standard pip install...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(REQ_PATH)], check=True, cwd=str(BASE_DIR))

    print("[D.O.N.N.A. Setup] Installing Playwright browsers...")
    subprocess.run([sys.executable, "-m", "playwright", "install"], check=True, cwd=str(BASE_DIR))

if platform.system() == "Windows":
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        postinstall = Path(sys.executable).parent / "Scripts" / "pywin32_postinstall.py"
        print(
            "\n[WARNING] pywin32 did not install correctly — desktop shortcut creation "
            "will fall back to a slower method that may not work on this machine.\n"
            "    Try fixing it manually with:\n"
            f'    "{sys.executable}" -m pip install --force-reinstall pywin32\n'
            f'    "{sys.executable}" "{postinstall}" -install\n'
        )

print("\n[OK] Setup complete!")
if UV_PATH:
    print("  • To launch D.O.N.N.A.:       uv run python run_microservices.py")
    print("  • With Desktop HUD:           uv run python run_microservices.py --with-ui")
    print("  • Headless (server-only):     uv run python run_microservices.py --no-audio")
else:
    print("  • To launch D.O.N.N.A.:       python run_microservices.py")
    print("  • With Desktop HUD:           python run_microservices.py --with-ui")
    print("  • Headless (server-only):     python run_microservices.py --no-audio")
