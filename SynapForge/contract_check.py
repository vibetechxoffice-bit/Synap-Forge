#!/usr/bin/env python3
"""
contract_check.py - automates the acceptance criteria.

  python contract_check.py            static checks (safe to run any time)
  python contract_check.py --live     also probes ports and the /config.json route

Result tags:  PASS | BUG (code defect) | CONFIG (settings) | DEPENDENCY (service not up)
Exit code 1 if anything is not PASS.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import urllib.request
from pathlib import Path

import synap_config as cfg

IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
ALLOWED = {"255.255.255.255"}  # broadcast mask only. 127.x and the wildcard address are BUGs too.
SKIP_DIRS = {
    ".git", "venv", ".venv", "env", "node_modules", "state", "__pycache__", "site-packages",
    "dist", "build", "llama", "vendor", "lib", "_internal", ".gradle",
}
SCAN_EXT = {".py", ".html", ".js", ".bat"}
MAX_LITERALS = 25

results = []


def add(tag: str, msg: str) -> None:
    results.append((tag, msg))
    print(f"[{tag:10}] {msg}")


def octets_ok(s: str) -> bool:
    return all(0 <= int(x) <= 255 for x in s.split("."))


def check_ports():
    try:
        cfg.validate_ports()
        add("PASS", "ports are valid and unique")
    except cfg.ConfigError as e:
        add("CONFIG", f"ports: {e}")


def check_published():
    ep = cfg.read_endpoint()
    if not ep:
        add("CONFIG", f"{cfg.endpoint_path()} missing or unreadable: RISA has not published")
        return None
    host = ep.get("host")
    if not host:
        add("CONFIG", "endpoint.json has no host")
        return None
    add("PASS", f"endpoint.json: host {host} (source: {ep.get('source')})")

    rm_path = cfg.role_map_path()
    try:
        rm = json.loads(rm_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        add("CONFIG", f"role_map.json unreadable: {e}")
        return host
    p = cfg.ports()
    bad = 0
    for role in cfg.ROLES:
        e = rm.get(role)
        if not isinstance(e, dict):
            add("CONFIG", f"role_map.json missing role '{role}'")
            bad += 1
            continue
        if e.get("host") != host or int(e.get("port", -1)) != p[role]:
            add("CONFIG", f"role_map '{role}' is {e.get('host')}:{e.get('port')}, "
                          f"expected {host}:{p[role]}")
            bad += 1
    if not bad:
        add("PASS", "role_map.json matches endpoint.json and the port contract")
    return host


def check_literals(root: Path):
    hits = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SCAN_EXT:
            continue
        if SKIP_DIRS & {part.lower() for part in path.relative_to(root).parts}:
            continue
        if path.name == Path(__file__).name:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for m in IP_RE.findall(line):
                if m not in ALLOWED and octets_ok(m):
                    hits.append(f"{path.relative_to(root)}:{n}: {m}")
    if hits:
        for h in hits[:MAX_LITERALS]:
            add("BUG", f"hardcoded address {h}")
        if len(hits) > MAX_LITERALS:
            add("BUG", f"... and {len(hits) - MAX_LITERALS} more")
    else:
        add("PASS", "no IP literals (including loopback/wildcard) in .py/.html/.js/.bat")


def check_live(host: str):
    p = cfg.ports()
    for role in cfg.ROLES:
        try:
            with socket.create_connection((host, p[role]), timeout=2):
                add("PASS", f"{role} listening on {host}:{p[role]}")
        except OSError:
            add("DEPENDENCY", f"{role} not reachable on {host}:{p[role]}")
    base = f"http://{host}:{p['studio']}"
    try:
        with urllib.request.urlopen(base + "/config.json", timeout=3) as r:
            body = r.read().decode("utf-8", "ignore")
        leaked = [m for m in IP_RE.findall(body) if m not in ALLOWED]
        if leaked:
            add("BUG", f"/config.json leaks addresses: {leaked}")
        else:
            add("PASS", "/config.json served and contains no addresses")
    except Exception as e:
        add("DEPENDENCY", f"/config.json not served by studio ({e})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--root", default=None)
    a = ap.parse_args()
    cfg.load_env()
    root = Path(a.root) if a.root else cfg.base_dir()
    check_ports()
    host = check_published()
    check_literals(root)
    if a.live:
        if host:
            check_live(host)
        else:
            add("DEPENDENCY", "skipping live checks: no published endpoint")
    bad = [r for r in results if r[0] != "PASS"]
    print(f"\n{len(results) - len(bad)} PASS, {len(bad)} not passing")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())