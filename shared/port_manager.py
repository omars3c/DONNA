"""
shared/port_manager.py — Cross-platform port inspection and stale process cleanup.
Ensures ports 8000-8007 are free before binding to avoid [Errno 10048] / WSAEADDRINUSE.
"""

import os
import sys
import time
import socket
import signal
import subprocess
from typing import Set


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if port can be connected to or bound to."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        if s.connect_ex((host, port)) == 0:
            return True
    return False


def get_pids_on_port(port: int) -> Set[int]:
    """Find all PIDs listening on the given TCP port."""
    pids = set()
    curr_pid = os.getpid()

    if sys.platform == "win32":
        try:
            res = subprocess.run(
                "netstat -ano",
                shell=True,
                capture_output=True,
                text=True,
                errors="replace",
            )
            for line in res.stdout.strip().splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0].upper() == "TCP" and "LISTENING" in parts:
                    local_addr = parts[1]
                    if local_addr.rsplit(":", 1)[-1] == str(port):
                        pid_str = parts[-1]
                        if pid_str.isdigit():
                            pid = int(pid_str)
                            if pid > 0 and pid != curr_pid:
                                pids.add(pid)
        except Exception:
            pass
    else:
        try:
            res = subprocess.run(
                ["lsof", "-t", f"-i:{port}"],
                capture_output=True,
                text=True,
            )
            for pid_str in res.stdout.strip().split():
                if pid_str.isdigit():
                    pid = int(pid_str)
                    if pid > 0 and pid != curr_pid:
                        pids.add(pid)
        except Exception:
            pass

    return pids


def free_port(port: int, service_name: str = "", verbose: bool = True) -> bool:
    """
    Terminates any stale processes occupying the target port, then waits
    until the OS fully releases the socket (handles TIME_WAIT on Windows).
    Returns True if port is free, False if occupied and could not be freed.
    """
    pids = get_pids_on_port(port)
    if not pids and not is_port_in_use(port):
        return True

    svc_label = f" ({service_name})" if service_name else ""
    for pid in pids:
        if verbose:
            print(f"🧹 Port {port}{svc_label} is occupied by PID {pid}. Freeing port...")
        if sys.platform == "win32":
            subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass

    # Wait for the OS to release the socket (TIME_WAIT on Windows can linger).
    # Poll up to 3 seconds in 0.5s increments.
    for attempt in range(6):
        time.sleep(0.5)
        remaining_pids = get_pids_on_port(port)
        if len(remaining_pids) == 0 and not is_port_in_use(port):
            return True
        if verbose and attempt == 0 and pids:
            print(f"⏳ Waiting for port {port}{svc_label} to be released by OS...")

    # Last-resort: try binding with SO_REUSEADDR — uvicorn does the same internally
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == "win32":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
        probe.close()
        return True
    except OSError:
        if verbose:
            print(f"⚠️  Port {port}{svc_label} still in use after cleanup — will retry at bind time.")
        return False
