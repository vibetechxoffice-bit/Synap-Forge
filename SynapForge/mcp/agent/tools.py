from typing import List, Dict, Any, Optional
"""Declarative tool registry - single source of truth for all MCP tools"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable
import json

@dataclass
class Tool:
    """Tool definition with schema, endpoint, and validation"""
    name: str
    description: str
    endpoint: str
    schema: Dict[str, Any] = field(default_factory=dict)
    required_params: list = field(default_factory=list)
    timeout: int = 30
    enabled: bool = True
    policy: str = "auto"  # "auto", "confirm", "restricted"
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate parameters against schema"""
        # Check required params
        for req in self.required_params:
            if req not in params:
                return False, f"Missing required parameter: {req}"
        
        # Type validation (basic)
        for key, value in params.items():
            if key in self.schema:
                expected_type = self.schema[key].get("type")
                if expected_type == "string" and not isinstance(value, str):
                    return False, f"Parameter {key} should be string, got {type(value).__name__}"
                elif expected_type == "number" and not isinstance(value, (int, float)):
                    return False, f"Parameter {key} should be number, got {type(value).__name__}"
        
        return True, None

# Tool Registry - Single source of truth
TOOLS = {
    "adb_devices": Tool(
        name="adb_devices",
        description="List connected Android devices",
        endpoint="/api/adb_devices",
        schema={},
        required_params=[]
    ),
    "adb_install": Tool(
        name="adb_install",
        description="Install APK on device",
        endpoint="/api/adb_install",
        schema={"path": {"type": "string", "description": "Path to APK file"}},
        required_params=["path"]
    ),
    "adb_shell": Tool(
        name="adb_shell",
        description="Run shell command on device",
        endpoint="/api/adb_shell",
        schema={"command": {"type": "string", "description": "Shell command to execute"}},
        required_params=["command"]
    ),
    "gradle_build": Tool(
        name="gradle_build",
        description="Build APK using Gradle",
        endpoint="/api/gradle_build",
        schema={"task": {"type": "string", "description": "Gradle task (default: assembleDebug)"}},
        required_params=[]
    ),
    "git_commit": Tool(
        name="git_commit",
        description="Commit changes to git",
        endpoint="/api/git_commit",
        schema={"message": {"type": "string", "description": "Commit message"}},
        required_params=["message"]
    ),
    "git_push": Tool(
        name="git_push",
        description="Push to remote repository",
        endpoint="/api/git_push",
        schema={},
        required_params=[]
    ),
    "search_memory": Tool(
        name="search_memory",
        description="Search memory for relevant information",
        endpoint="/api/search_memory",
        schema={"query": {"type": "string", "description": "Search query"}},
        required_params=["query"]
    ),
    "ingest_memory": Tool(
        name="ingest_memory",
        description="Store information in memory",
        endpoint="/api/ingest_memory",
        schema={"content": {"type": "string", "description": "Content to store"}},
        required_params=["content"]
    ),
    "read_file": Tool(
        name="read_file",
        description="Read a file from the filesystem",
        endpoint="/api/read_file",
        schema={"file_path": {"type": "string", "description": "Absolute path to the file"}},
        required_params=["file_path"]
    ),
    "list_directory": Tool(
        name="list_directory",
        description="List the contents of a directory",
        endpoint="/api/list_directory",
        schema={"directory_path": {"type": "string", "description": "Absolute path to the directory"}},
        required_params=["directory_path"]
    ),
    "write_file": Tool(
        name="write_file",
        description="Write content to a file on the filesystem",
        endpoint="/api/write_file",
        schema={"file_path": {"type": "string", "description": "Target file path"}, "content": {"type": "string", "description": "File content"}},
        required_params=["file_path", "content"]
    ),
    "search_code": Tool(
        name="search_code",
        description="Search source code database for matching terms",
        endpoint="/api/search_code",
        schema={"query": {"type": "string", "description": "Code search query"}, "limit": {"type": "number", "description": "Max results"}},
        required_params=["query"]
    ),
    "knowledge_stats": Tool(
        name="knowledge_stats",
        description="Get knowledge base index and document statistics",
        endpoint="/api/knowledge_stats",
        schema={},
        required_params=[]
    ),
    "smart_fix": Tool(
        name="smart_fix",
        description="Analyze an error message and retrieve suggested smart fix solution",
        endpoint="/api/smart_fix",
        schema={"error": {"type": "string", "description": "Error trace or message to analyze"}},
        required_params=["error"]
    ),
    "get_memory_stats": Tool(
        name="get_memory_stats",
        description="Retrieve current memory fragment statistics and system state",
        endpoint="/api/get_memory_stats",
        schema={},
        required_params=[]
    ),
    "get_weaver_status": Tool(
        name="get_weaver_status",
        description="Retrieve active memory Weaver background status",
        endpoint="/api/get_weaver_status",
        schema={},
        required_params=[]
    ),
    "get_recent_patterns": Tool(
        name="get_recent_patterns",
        description="Retrieve recently woven memory patterns",
        endpoint="/api/get_recent_patterns",
        schema={"limit": {"type": "number", "description": "Max pattern count"}},
        required_params=[]
    ),
    "voice_listen": Tool(
        name="voice_listen",
        description="Listen and transcribe audio input",
        endpoint="/api/voice_listen",
        schema={"duration": {"type": "number", "description": "Listening duration in seconds"}},
        required_params=[]
    ),
    "voice_speak": Tool(
        name="voice_speak",
        description="Synthesize speech from text",
        endpoint="/api/voice_speak",
        schema={"text": {"type": "string", "description": "Text to synthesize"}},
        required_params=["text"]
    ),
    "check_port": Tool(
        name="check_port",
        description="Check if a network port is reachable",
        endpoint="/api/check_port",
        schema={"host": {"type": "string", "description": "Target host"}, "port": {"type": "number", "description": "Target port"}},
        required_params=["port"]
    ),
}

def get_tool(name: str) -> Optional[Tool]:  # ← keep this one (first version)
    """Get tool by name"""
    return TOOLS.get(name)

def list_tools() -> Dict[str, Tool]:
    """List all tools"""
    return TOOLS

def generate_tools_prompt() -> str:  # ← keep this one (first version)
    """Generate system prompt from tool registry"""
    lines = []
    for name, tool in TOOLS.items():
        params_desc = ", ".join(tool.required_params)
        lines.append(f"{name} - {tool.description} (required: {params_desc or 'none'})")
    return "\n".join(lines)

def get_openai_tools() -> List[Dict[str, Any]]:
    """Get all tools in OpenAI function-calling format"""
    tools = []
    for tool in TOOLS.values():
        if not tool.enabled:
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.schema or {"type": "object", "properties": {}}
            }
        })
    return tools
    
    # ── Tool Policy Registry ──────────────────────────────────────
# Single source of truth for tool execution policy.
# "auto"       = execute without additional approval
# "confirm"    = require user confirmation
# "restricted" = execution blocked unless explicitly authorized

TOOL_POLICY: Dict[str, str] = {}

for name, tool in TOOLS.items():
    TOOL_POLICY[name] = tool.policy