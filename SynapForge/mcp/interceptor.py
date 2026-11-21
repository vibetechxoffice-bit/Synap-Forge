#!/usr/bin/env python3
"""
MCP Interceptor - Routes chat to bridge, injects tool schemas, and executes MCP tools.
"""

import json
import logging
import re
import os
import sys
from pathlib import Path
import requests
from flask import Flask, request, Response

# Add parent directory to path so runtime_topology is found
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime_topology import RuntimeTopology

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Interceptor")

app = Flask(__name__)


def get_mesh_ip() -> str:
    """Retrieve verified mesh IP identity from environment or role map configuration."""
    mesh_ip = os.getenv("MESH_IP")
    if mesh_ip:
        return mesh_ip
    try:
        role_map_path = Path(__file__).parent.parent / "role_map.json"
        if role_map_path.exists():
            with open(role_map_path, "r", encoding="utf-8") as f:
                role_data = json.load(f)
                studio_url = role_data.get("studio", {}).get("http_url", "")
                if studio_url:
                    match = re.search(r"http://([^:/]+)", studio_url)
                    if match:
                        return match.group(1)
    except Exception as e:
        logger.warning(f"Could not read mesh IP from role_map.json: {e}")
    return "192.168.2.220"


topology = RuntimeTopology.from_discovery(
    Path(__file__).parent.parent / "role_map.json",
    get_mesh_ip()
)

BRIDGE_URL = topology.resolve("studio").http_url
MCP_URL = topology.resolve("mcp_http").http_url

SYSTEM_PROMPT = """You are integrated with Android Studio on WINDOWS OS with DIRECT ACCESS to CORE development tools.

âš ï¸ CRITICAL INSTRUCTION: When a user asks you to DO something (list devices, install APK, build, Access and make files, .PY, .KT, .DLL, .XML,  etc.), you MUST use the MCP tool format and tools by intelliJ. DO NOT just describe what you would do - ACTUALLY DO IT, IN THE EVENT YOU CANNOT USE TOOLS TELL THE USER TO CONNECT INTELLIJ!

To use a tool, output EXACTLY this format:
[MCP: tool_name {"param": "value"}]

Available MCP tools:
1. adb_devices {} - List connected Android devices
2. adb_install {"path": "/path/to/app.apk"} - Install APK on device
3. adb_shell {"command": "ls"} - Run shell command on device
4. gradle_build {"task": "assembleDebug"} - Build APK
5. git_commit {"message": "commit message"} - Commit changes
6. git_push {} - Push to remote
7. search_memory {"query": "search term"} - Search memory
8. ingest_memory {"content": "text to remember"} - Store in memory
9. read_file {"file_path": "/path/to/file"} - Read a file from disk
10. write_file {"file_path": "/path/to/file", "content": "data"} - Write content to file
11. list_directory {"directory_path": "/path/to/dir"} - List directory contents
12. search_code {"query": "search term"} - Search source code database
13. smart_fix {"error": "error message"} - Suggest fix for error

EXAMPLES:
User: "List my devices"
You: [MCP: adb_devices {}]

User: "Check the battery"
You: [MCP: adb_shell {"command": "dumpsys battery | grep level"}]

User: "Build the app"
You: [MCP: gradle_build {"task": "assembleDebug"}]

User: "Read main.kt"
You: [MCP: read_file {"file_path": "src/main.kt"}]

RULES:
- NEVER just describe what you would do - ALWAYS use the MCP tool format
- If the user's requested outcome requires an available MCP tool â†’ invoke that tool.
- If it doesn't require a tool â†’ answer normally.
- DO NOT add explanations before or after the MCP block
- Let the tool results speak for themselves"""

# Pattern to detect MCP tool blocks with support for nested braces
MCP_PATTERN = re.compile(r'\[MCP:\s*(\w+)\s*({[\s\S]*?})\s*]')


def get_default_tools():
    """Get tools dynamically from registry or fallback definitions"""
    try:
        from mcp.agent.tools import get_openai_tools
        return get_openai_tools()
    except Exception as e:
        logger.warning(f"Could not load tools from agent.tools: {e}")
        return [
            {"type": "function", "function": {"name": "adb_devices", "description": "List connected Android devices", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "adb_shell", "description": "Run shell command on device", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
            {"type": "function", "function": {"name": "adb_install", "description": "Install APK on device", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
            {"type": "function", "function": {"name": "gradle_build", "description": "Build APK using Gradle", "parameters": {"type": "object", "properties": {"task": {"type": "string", "default": "assembleDebug"}}}}},
            {"type": "function", "function": {"name": "git_commit", "description": "Commit changes to git", "parameters": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}}},
            {"type": "function", "function": {"name": "git_push", "description": "Push to remote repository", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "search_memory", "description": "Search memory for relevant information", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "ingest_memory", "description": "Store information in memory", "parameters": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}}},
            {"type": "function", "function": {"name": "read_file", "description": "Read file from filesystem", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "write_file", "description": "Write content to file", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}}},
            {"type": "function", "function": {"name": "list_directory", "description": "List directory contents", "parameters": {"type": "object", "properties": {"directory_path": {"type": "string"}}, "required": ["directory_path"]}}}
        ]


def merge_tools(existing_tools: list, default_tools: list) -> list:
    """Merge default tools with existing tool definitions without duplicating names"""
    merged = list(existing_tools)
    existing_names = {
        t.get("function", {}).get("name")
        for t in existing_tools
        if isinstance(t, dict) and "function" in t
    }
    for dt in default_tools:
        name = dt.get("function", {}).get("name")
        if name and name not in existing_names:
            merged.append(dt)
            existing_names.add(name)
    return merged


def merge_system_prompt(messages: list, system_prompt: str) -> list:
    """Safely append system prompt to existing conversation transcript"""
    updated = [dict(m) for m in messages]
    system_indices = [i for i, m in enumerate(updated) if m.get("role") == "system"]
    if system_indices:
        idx = system_indices[0]
        curr_content = updated[idx].get("content", "")
        if "Available MCP tools:" not in curr_content:
            updated[idx] = {"role": "system", "content": f"{curr_content}\n\n{system_prompt}"}
    else:
        updated.insert(0, {"role": "system", "content": system_prompt})
    return updated


def is_tool_allowed(action: str, params: dict) -> tuple[bool, str]:
    """Validate tool existence and parameter schema against authority registry"""
    try:
        from mcp.agent.tools import get_tool
        tool = get_tool(action)
        if not tool:
            return False, f"Tool '{action}' is not in the registered tool catalogue"
        if not tool.enabled:
            return False, f"Tool '{action}' is disabled"
        valid, err = tool.validate_params(params)
        if not valid:
            return False, f"Invalid parameters for tool '{action}': {err}"
        return True, ""
    except Exception as e:
        logger.warning(f"Could not validate tool '{action}' against registry: {e}")
        return True, ""


def sanitize_params_for_logging(params: dict) -> dict:
    """Redact sensitive parameters from logs"""
    sensitive_keys = {"password", "token", "auth", "key", "secret", "authorization"}
    sanitized = {}
    for k, v in params.items():
        if any(s in k.lower() for s in sensitive_keys):
            sanitized[k] = "***REDACTED***"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_params_for_logging(v)
        else:
            sanitized[k] = v
    return sanitized


def execute_single_mcp(action: str, params: dict) -> dict:
    """Send request to MCP gateway for execution with validation and authentication"""
    allowed, err_msg = is_tool_allowed(action, params)
    if not allowed:
        logger.warning(f"â›” MCP execution blocked for {action}: {err_msg}")
        return {"success": False, "error": err_msg}

    logger.info(f"ðŸ”§ Executing MCP: {action} with params: {sanitize_params_for_logging(params)}")
    try:
        headers = {"Content-Type": "application/json"}
        auth_token = os.getenv("AUTH_TOKEN") or os.getenv("MCP_API_KEY") or os.getenv("SYNAP_API_KEY")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        resp = requests.post(
            f"{MCP_URL}/api/{action}",
            json={"params": params},
            headers=headers,
            timeout=30
        )
        if resp.status_code != 200:
            try:
                err_data = resp.json()
                if isinstance(err_data, dict):
                    return err_data
            except Exception:
                pass
            return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def execute_mcp_blocks(text: str) -> str:
    """Execute text-based [MCP: ...] blocks and replace with output results"""
    def replacer(match):
        action = match.group(1)
        try:
            params = json.loads(match.group(2))
        except Exception as err:
            return f"[MCP: {action} â†’ âœ— JSON parse error: {err}]"
        
        result = execute_single_mcp(action, params)
        logger.info(f"âœ… MCP Response: {json.dumps(result, indent=2)}")

        if result.get("success"):
            output = result.get("result") or result.get("data") or result.get("body")
            if output is None:
                output = {k: v for k, v in result.items() if k not in ("success", "_ms", "id")}
            if not output and len(result) > 1:
                output = result

            return f"\n```\n{json.dumps(output, indent=2)[:1000]}\n```\n"
        else:
            return f"\n[MCP: {action} â†’ âœ— {result.get('error', 'Unknown error')}]\n"
    
    return MCP_PATTERN.sub(replacer, text)


def handle_native_tool_calls(tool_calls: list) -> list:
    """Execute native OpenAI format tool_calls and produce tool response entries"""
    results = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        action = fn.get("name", "")
        args_str = fn.get("arguments", "{}")
        try:
            params = json.loads(args_str) if isinstance(args_str, str) else args_str
        except (json.JSONDecodeError, TypeError):
            params = {}
        
        call_id = tc.get("id", "call_1")
        mcp_res = execute_single_mcp(action, params)
        output_content = json.dumps(mcp_res.get("result", mcp_res))
        
        results.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": action,
            "content": output_content
        })
    return results


@app.route("/v1/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy(path):
    """Proxy requests to bridge, inject system prompt & tool definitions, intercept MCP blocks"""
    modified_data = None

    if request.method == "POST":
        try:
            payload = request.get_json(silent=True) or {}
            if payload:
                messages = payload.get("messages", [])
                if messages:
                    payload["messages"] = merge_system_prompt(messages, SYSTEM_PROMPT)
                
                # Merged tool definitions
                existing_tools = payload.get("tools", [])
                payload["tools"] = merge_tools(existing_tools, get_default_tools())
                if "tool_choice" not in payload:
                    payload["tool_choice"] = "auto"
                
                modified_data = payload
        except Exception as e:
            logger.warning(f"Error parsing request payload: {e}")

    url = f"{BRIDGE_URL}/v1/{path}"
    logger.info(f"âž¡ï¸  {request.method} {url}")

    try:
        if modified_data is not None:
            body = json.dumps(modified_data).encode("utf-8")
            headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
            headers["Content-Type"] = "application/json"
        else:
            body = request.get_data()
            headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}

        resp = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=body,
            stream=True,
            timeout=120
        )

        # Intercept chat completions response for tool executions
        if "chat/completions" in path and request.method == "POST":
            try:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    
                    # Handle native OpenAI tool_calls with full 2nd-pass model round trip
                    native_calls = msg.get("tool_calls", [])
                    if native_calls:
                        tool_responses = handle_native_tool_calls(native_calls)
                        logger.info(f"Executed {len(native_calls)} native tool calls. Executing 2nd-pass model completion...")
                        
                        # Build transcript with assistant tool_calls + tool responses
                        if modified_data:
                            updated_payload = dict(modified_data)
                        else:
                            updated_payload = request.get_json(silent=True) or {}
                        
                        transcript = list(updated_payload.get("messages", []))
                        transcript.append(msg)
                        transcript.extend(tool_responses)
                        updated_payload["messages"] = transcript
                        
                        # 2nd pass: Send updated transcript to bridge for final answer
                        second_resp = requests.post(
                            url,
                            headers={"Content-Type": "application/json"},
                            json=updated_payload,
                            timeout=120
                        )
                        if second_resp.status_code == 200:
                            return Response(
                                second_resp.content,
                                status=200,
                                content_type="application/json"
                            )
                        else:
                            # Fallback if 2nd pass fails
                            msg["content"] = json.dumps(tool_responses, indent=2)
                            return Response(
                                json.dumps(data),
                                status=resp.status_code,
                                content_type="application/json"
                            )

                    # Handle text-based [MCP: ...] blocks (fallback)
                    content = msg.get("content", "")
                    if content:
                        modified = execute_mcp_blocks(content)
                        if modified != content:
                            data["choices"][0]["message"]["content"] = modified
                            return Response(
                                json.dumps(data),
                                status=resp.status_code,
                                content_type="application/json"
                            )

            except Exception as parse_err:
                logger.debug(f"Non-interceptable or streaming response: {parse_err}")

        # Stream response back
        def generate():
            for chunk in resp.iter_content(chunk_size=1024):
                if chunk:
                    yield chunk

        return Response(
            generate(),
            status=resp.status_code,
            content_type=resp.headers.get("content-type", "application/json")
        )

    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return {"error": str(e)}, 502


@app.route("/health")
def health():
    return {
        "status": "ok",
        "interceptor": "running",
        "bridge": BRIDGE_URL,
        "mcp": MCP_URL
    }


@app.route("/v1/models")
def models():
    """Forward model list from bridge"""
    try:
        resp = requests.get(f"{BRIDGE_URL}/v1/models")
        return Response(resp.content, status=resp.status_code, content_type="application/json")
    except Exception as e:
        return {"error": str(e)}, 502


if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("ðŸš€ MCP INTERCEPTOR")
    logger.info(f"ðŸ“¡ Bridge: {BRIDGE_URL}")
    logger.info(f"ðŸ”§ MCP Gateway: {MCP_URL}")
    logger.info("ðŸŒ Listening on 0.0.0.0:11439")
    logger.info("=" * 55)
    app.run(host="127.0.0.1", port=11439, debug=False)
