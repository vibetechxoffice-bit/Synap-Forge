#!/usr/bin/env python3
"""
synap_config.py - Synap-Forge configuration contract (stdlib only).

Ownership
  .env           deployment settings. The setup wizard writes it; humans may edit it.
  endpoint.json  (next to role_map.json) the runtime address. RISA publishes it. CONSUMERS READ THIS.
  role_map.json  role -> endpoint. RISA publishes it.

Launcher, synap_server, interceptor, MCP and the dashboard call this module.
None of them may invent a host or a port.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

# One name per port. "ollama" is the offline personality runner (11435, "ALAMA" in
# conversation). The interceptor (11439) is a different role; never reuse a port.
ROLES = ("ollama", "studio", "llm", "mcp_socket", "interceptor", "mcp_http", "mcp_ws")

DEFAULT_PORTS: Dict[str, int] = {
    "ollama": 11435,
    "studio": 11436,       # synap_server.py: the "bridge" / thought-loop server
    "llm": 11437,          # llama.cpp
    "mcp_socket": 11438,   # MCP socket server behind the gateway
    "interceptor": 11439,
    "mcp_http": 11440,
    "mcp_ws": 11441,
}

_PORT_ENV = {
    "ollama": ("OLLAMA_PORT", "ALAMA_PORT", "OLLAMA_FALLBACK_PORT"),
    "studio": ("STUDIO_PORT", "SYNAP_CORE_PORT"),
    "llm": ("LLM_PORT",),
    "mcp_socket": ("MCP_SOCKET_PORT",),
    "interceptor": ("INTERCEPTOR_PORT",),
    "mcp_http": ("MCP_HTTP_PORT",),
    "mcp_ws": ("MCP_WS_PORT",),
}

SCHEME = {"mcp_ws": "ws", "mcp_socket": "tcp"}  # everything else is http


class ConfigError(RuntimeError):
    pass


# ---------------------------------------------------------------- locations
def base_dir() -> Path:
    return Path(os.getenv("SYNAP_BASE_DIR") or Path(__file__).resolve().parent)


def state_dir() -> Path:
    return Path(os.getenv("SYNAP_STATE_DIR") or (base_dir() / "state"))


def endpoint_path() -> Path:
    return base_dir() / "endpoint.json"


def role_map_path() -> Path:
    return base_dir() / "role_map.json"


# ---------------------------------------------------------------- .env
def load_env(path: Optional[os.PathLike] = None, override: bool = False) -> Dict[str, str]:
    """Minimal .env reader. Never overrides real environment variables unless asked."""
    p = Path(path) if path else base_dir() / ".env"
    loaded: Dict[str, str] = {}
    if not p.is_file():
        return loaded
    for raw in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if not key:
            continue
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]
        else:
            val = re.split(r"\s+#", val, maxsplit=1)[0].strip()
        loaded[key] = val
        if override or key not in os.environ:
            os.environ[key] = val
    return loaded


# ---------------------------------------------------------------- ports
def ports() -> Dict[str, int]:
    out: Dict[str, int] = {}
    for role in ROLES:
        raw, used = None, _PORT_ENV[role][0]
        for name in _PORT_ENV[role]:
            v = os.getenv(name, "").strip()
            if v:
                raw, used = v, name
                break
        try:
            out[role] = int(raw) if raw else DEFAULT_PORTS[role]
        except ValueError:
            raise ConfigError(f"{used} must be an integer, got {raw!r}")
    return out


def validate_ports(p: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    p = p or ports()
    seen: Dict[int, str] = {}
    for role, port in p.items():
        if not 1 <= port <= 65535:
            raise ConfigError(f"port for '{role}' out of range: {port}")
        if port in seen:
            raise ConfigError(f"port {port} is assigned to both '{seen[port]}' and '{role}'")
        seen[port] = role
    return p


def bind_host() -> str:
    """Address a service should listen on (not the address clients should use)."""
    return os.getenv("BIND_HOST", "").strip() or "0.0.0.0"


# ---------------------------------------------------------------- published endpoint
def read_endpoint() -> Optional[dict]:
    try:
        return json.loads(endpoint_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def host(strict: bool = False) -> str:
    """Address clients should use. Source of truth: endpoint.json published by RISA."""
    ep = read_endpoint()
    if ep and ep.get("host"):
        return str(ep["host"])
    adv = os.getenv("ADVERTISE_HOST", "").strip()
    if adv:
        return adv
    if strict:
        raise ConfigError(
            f"{endpoint_path()} not found. RISA has not published an endpoint "
            "(run: python risa_v3.2.py --publish)."
        )
    return "127.0.0.1"


def url(role: str, strict: bool = False) -> str:
    if role not in ROLES:
        raise ConfigError(f"unknown role '{role}'. Known: {', '.join(ROLES)}")
    return f"{SCHEME.get(role, 'http')}://{host(strict)}:{ports()[role]}"


# ---------------------------------------------------------------- browser-safe config
def public_config(agent_name: Optional[str] = None) -> dict:
    """Served at /config.json. Names and links only. Never hosts, ports, keys or paths."""
    name = (
        agent_name
        or os.getenv("AGENT_NAME")
        or os.getenv("ASSISTANT_NAME")
        or "Assistant"
    )
    return {
        "schema": 1,
        "agent_name": name,
        "user_tag": os.getenv("USER_TAG", "User"),
        "forum_url": os.getenv("FORUM_URL", ""),
    }