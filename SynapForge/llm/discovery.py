# llm/discovery.py
import os
import sys
import time
import socket
import json
from pathlib import Path
from typing import List, Optional

def get_runtime_root() -> Path:
    """Safely get the workspace root folder."""
    base_dir_env = os.getenv("SYNAP_BASE_DIR")
    if base_dir_env and Path(base_dir_env).exists():
        return Path(base_dir_env)
    return Path(__file__).resolve().parents[1]

def get_discovered_model_url() -> str:
    """
    Unified Discovery Authority.
    Checks environment override -> checks role_map.json -> checks active ports.
    """
    # 1. Environment Override
    env_override = os.getenv("LOCAL_LLM_URL") or os.getenv("PERSONAL_CLOUD_URL")
    if env_override:
        return env_override

    # 2. Topology Discovery via role_map.json
    root = get_runtime_root()
    role_map_path = root / "role_map.json"
    if role_map_path.exists():
        try:
            with open(role_map_path, 'r') as f:
                role_map = json.load(f)
            
            # Check the structured 'llm' payload dictionary if present
            if "llm" in role_map and isinstance(role_map["llm"], dict):
                llm_val = role_map["llm"]
                url = llm_val.get("http_url") or llm_val.get("url")
                if url:
                    url_clean = url.rstrip("/")
                    return url_clean if url_clean.endswith("/v1") else f"{url_clean}/v1"
                llm_port = llm_val.get("port")
                if llm_port:
                    return f"http://127.0.0.1:{llm_port}/v1"
            
            # Fallback parsing for flat mapped attributes
            for key in ["llama", "ollama", "mcp_http"]:
                val = role_map.get(key)
                if val:
                    if isinstance(val, dict):
                        # Extract string port or look up URL if nested block exists
                        url = val.get("http_url") or val.get("url")
                        if url:
                            url_clean = url.rstrip("/")
                            return url_clean if url_clean.endswith("/v1") else f"{url_clean}/v1"
                        port = val.get("port")
                        if port: return f"http://127.0.0.1:{port}/v1"
                    else:
                        return f"http://127.0.0.1:{val}/v1"
        except Exception:
            pass

    # 3. Port Candidate Probing Fallback
    candidates = [11437, 11434, 8000, 5000, 1234]
    for port in candidates:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return f"http://127.0.0.1:{port}/v1"
        except OSError:
            continue

    # Clean default return
    return "http://127.0.0.1:11437/v1"

def wait_for_model_readiness(url: str, timeout: int = 180) -> bool:
    """Poll the API with a test completion query to confirm 7B model loading & prewarm is complete."""
    import urllib.request
    import urllib.error
    
    base_url = url.rstrip("/").rstrip("/v1")
    chat_endpoint = f"{base_url}/v1/chat/completions"
    
    # Prewarm with system prompt so KV cache is primed for the actual system context
    system_prompt = "You are Assistant, a sovereign AI personality."
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Hello"}
        ],
        "max_tokens": 1
    }).encode("utf-8")
    
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                chat_endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    body = json.loads(response.read().decode('utf-8'))
                    choices = body.get("choices", [])
                    if choices and isinstance(choices, list):
                        msg = choices[0].get("message") or choices[0].get("delta") or {}
                        if "content" in msg or "role" in msg:
                            return True
        except (urllib.error.HTTPError, urllib.error.URLError, Exception):
            pass
        time.sleep(3.0)
    return False
