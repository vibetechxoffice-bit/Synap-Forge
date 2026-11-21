#!/usr/bin/env python3
"""
risa_publish.py - RISA's publishing responsibility.

RISA resolves the address once, then publishes:
  endpoint.json         (written LAST; it is the commit marker consumers read)
  role_map.json         (same schema RuntimeTopology already consumes: role -> {host, port, ...})

It does NOT touch .env (the wizard owns that) and does NOT patch source files.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

import synap_config as cfg


class PublishError(RuntimeError):
    pass


_HOSTNAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9\-.]{0,251}[A-Za-z0-9])?")


def valid_host(h: str) -> bool:
    """A publishable address is a real mesh/LAN address or hostname. Never loopback,
    never a wildcard, never 'localhost'."""
    if not h or h.lower() == "localhost":
        return False
    try:
        ip = ipaddress.ip_address(h)
        return not (ip.is_loopback or ip.is_unspecified or ip.is_multicast)
    except ValueError:
        return bool(_HOSTNAME.fullmatch(h))


def resolve_host(
    mesh_ip: Optional[str],
    current_endpoint: Optional[str],
    environ: Optional[dict] = None,
) -> Tuple[str, str]:
    """Priority: explicit operator override > Tailscale > local address."""
    env = os.environ if environ is None else environ
    adv = (env.get("ADVERTISE_HOST") or "").strip()
    if adv:
        host, source = adv, "override"
    elif mesh_ip:
        host, source = mesh_ip, "tailscale"
    elif current_endpoint:
        host, source = current_endpoint, "local"
    else:
        raise PublishError("no usable host: ADVERTISE_HOST unset, Tailscale inactive, no local address")
    if not valid_host(host):
        raise PublishError(f"refusing to publish invalid host {host!r} (source: {source})")
    return host, source


def build_role_map(host: str, p: Dict[str, int], model: str = "default") -> dict:
    rm: dict = {}
    for role in cfg.ROLES:
        proto = cfg.SCHEME.get(role, "http")
        entry = {"host": host, "port": p[role], "protocol": proto}
        if proto == "http":
            entry["http_url"] = f"http://{host}:{p[role]}"
        elif proto == "ws":
            entry["ws_url"] = f"ws://{host}:{p[role]}"
        rm[role] = entry
    rm["llm"].update({"provider": "llama.cpp", "model": model})
    rm["ollama"].update({"provider": "ollama"})
    return rm


def build_endpoint(host: str, source: str, p: Dict[str, int], extra: Optional[dict] = None) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ep = {
        "schema": 1,
        "host": host,
        "source": source,
        "ports": p,
        "urls": {r: f"{cfg.SCHEME.get(r, 'http')}://{host}:{p[r]}" for r in cfg.ROLES},
        "node_id": os.getenv("NODE_ID", ""),
        "published_at": now,
        "updated_at": now,  # legacy name used by earlier RISA output
    }
    ep.update(extra or {})
    return ep


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def publish(
    mesh_ip: Optional[str],
    current_endpoint: Optional[str],
    base_dir: Optional[Path] = None,
    state_dir: Optional[Path] = None,   # kept for compatibility; endpoint.json lives next to role_map.json
    dry_run: bool = False,
    extra: Optional[dict] = None,
) -> dict:
    """Resolve, validate and publish. Raises PublishError instead of writing bad data."""
    try:
        p = cfg.validate_ports()
    except cfg.ConfigError as e:
        raise PublishError(str(e))

    host, source = resolve_host(mesh_ip, current_endpoint)
    base = Path(base_dir) if base_dir else cfg.base_dir()
    rm_path, ep_path = base / "role_map.json", base / "endpoint.json"

    model = (os.getenv("MODEL_NAME") or os.getenv("SYNAP_MODEL_ALIAS")
             or os.getenv("AGENT_NAME") or "default")
    role_map = build_role_map(host, p, model)
    endpoint = build_endpoint(host, source, p, extra)

    old_rm, old_ep = _read(rm_path), _read(ep_path)
    rm_changed = old_rm != role_map
    ep_changed = (old_ep is None) or any(
        old_ep.get(k) != endpoint.get(k)
        for k in ("host", "source", "ports", "urls", *(extra or {}).keys())
    )

    result = {
        "host": host,
        "source": source,
        "changed": bool(rm_changed or ep_changed),
        "role_map_path": str(rm_path),
        "endpoint_path": str(ep_path),
        "dry_run": dry_run,
    }
    if dry_run:
        return result

    if rm_changed:
        if rm_path.exists():
            try:
                (rm_path.with_name(rm_path.name + ".bak")).write_bytes(rm_path.read_bytes())
            except OSError:
                pass
        _atomic_write_json(rm_path, role_map)
    if ep_changed:
        _atomic_write_json(ep_path, endpoint)  # last: marks the publish complete
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish endpoint.json and role_map.json")
    ap.add_argument("--mesh-ip")
    ap.add_argument("--local-ip", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cfg.load_env()
    try:
        r = publish(a.mesh_ip, a.local_ip, dry_run=a.dry_run)
    except PublishError as e:
        print(f"PUBLISH FAILED: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())