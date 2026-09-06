"""
Model Context Protocol (MCP) Client Engine for D.O.N.N.A. (Ported from OpenClaw MCP Suite)
Connects Donna to the global MCP ecosystem (PostgreSQL, SQLite, Filesystem, Brave, Puppeteer, GitHub, etc.)
over standard JSON-RPC STDIO / SSE transports.
"""

from __future__ import annotations

import os
import sys
import json
import asyncio
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
MCP_CONFIG_FILE = BASE_DIR / "config" / "mcp_servers.json"


class MCPServerProcess:
    def __init__(self, name: str, command: str, args: List[str], env: Optional[dict] = None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env or {}
        self.process: Optional[asyncio.subprocess.Process] = None
        self._request_id: int = 0
        self._tools: List[dict] = []

    async def start(self) -> bool:
        try:
            full_env = os.environ.copy()
            full_env.update(self.env)
            self.process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=full_env,
            )
            print(f"[MCPEngine] Started MCP server '{self.name}' (PID: {self.process.pid})")
            return True
        except Exception as e:
            print(f"[MCPEngine] Failed to start MCP server '{self.name}': {e}")
            return False

    async def send_rpc(self, method: str, params: Optional[dict] = None) -> Optional[dict]:
        if not self.process or not self.process.stdin or not self.process.stdout:
            return None

        self._request_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }
        data = json.dumps(req) + "\n"
        try:
            self.process.stdin.write(data.encode("utf-8"))
            await self.process.stdin.drain()

            line = await self.process.stdout.readline()
            if not line:
                return None
            return json.loads(line.decode("utf-8"))
        except Exception as e:
            print(f"[MCPEngine] RPC error on '{self.name}': {e}")
            return None

    async def stop(self):
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception:
                pass


class MCPEngine:
    _instance: Optional[MCPEngine] = None

    def __init__(self):
        self._servers: Dict[str, MCPServerProcess] = {}
        self._tools_cache: List[dict] = []
        self._load_config()

    @classmethod
    def get_instance(cls) -> MCPEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_config(self):
        if not MCP_CONFIG_FILE.exists():
            default_cfg = {
                "mcpServers": {
                    # Example: "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "c:/fryday v1"]}
                }
            }
            MCP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            MCP_CONFIG_FILE.write_text(json.dumps(default_cfg, indent=4), encoding="utf-8")

        try:
            cfg = json.loads(MCP_CONFIG_FILE.read_text(encoding="utf-8"))
            for name, s_cfg in cfg.get("mcpServers", {}).items():
                self._servers[name] = MCPServerProcess(
                    name=name,
                    command=s_cfg.get("command", ""),
                    args=s_cfg.get("args", []),
                    env=s_cfg.get("env", {}),
                )
        except Exception as e:
            print(f"[MCPEngine] Error loading mcp_servers.json: {e}")

    def list_servers(self) -> List[dict]:
        return [{"name": name, "running": s.process is not None} for name, s in self._servers.items()]

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        server = self._servers.get(server_name)
        if not server:
            return f"MCP server '{server_name}' not configured."
        if not server.process:
            ok = await server.start()
            if not ok:
                return f"Could not start MCP server '{server_name}'."

        res = await server.send_rpc("tools/call", {"name": tool_name, "arguments": arguments})
        if not res or "result" not in res:
            return f"MCP call failed: {res.get('error') if res else 'No response'}"
        return json.dumps(res["result"], ensure_ascii=False)


mcp_engine = MCPEngine.get_instance()
