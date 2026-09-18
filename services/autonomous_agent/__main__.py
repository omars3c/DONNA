import sys
import uvicorn
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
from shared.config import AUTONOMOUS_HOST, AUTONOMOUS_PORT

if __name__ == "__main__":
    from shared.port_manager import free_port
    free_port(AUTONOMOUS_PORT, "AutonomousAgent")
    print(f"Starting Autonomous Agent Service on {AUTONOMOUS_HOST}:{AUTONOMOUS_PORT}...")
    uvicorn.run("services.autonomous_agent.app:app", host=AUTONOMOUS_HOST, port=AUTONOMOUS_PORT)
