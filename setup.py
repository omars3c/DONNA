import subprocess
import sys
import platform
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

print("Installing requirements...")
subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(REQ_PATH)], check=True, cwd=str(BASE_DIR))

print("Installing Playwright browsers...")
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
print("  • To launch D.O.N.N.A.:       python run_microservices.py")
print("  • Headless (server-only):    python run_microservices.py --no-ui")

