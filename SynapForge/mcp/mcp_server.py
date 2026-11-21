#!/usr/bin/env python3

# Fix import paths - add .consciousness_engine to Python path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / ".consciousness_engine"))
sys.path.insert(0, str(Path(__file__).parent.parent))

"""
MCP GATEWAY â€” Port 11440
WebSocket + HTTP bridge between Synap-Forge UI and MCP Server
"""

import asyncio
import copy
import json
import logging
import os
import secrets
import socket
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from threading import Thread, Lock

# WebSocket
try:
    import websockets
    from websockets.server import serve
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

# HTTP
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

class SingleInstanceLock:
    def __init__(self, lock_file_path):
        self.lock_file_path = Path(lock_file_path)
        self.file_handle = None

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        try:
            if os.name == "nt":
                import ctypes
                h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if h:
                    ctypes.windll.kernel32.CloseHandle(h)
                    return True
                return False
            else:
                os.kill(pid, 0)
                return True
        except Exception:
            return False

    def acquire(self) -> bool:
        try:
            self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
            if self.lock_file_path.exists():
                try:
                    content = self.lock_file_path.read_text(encoding="utf-8").strip()
                    if content.isdigit():
                        existing_pid = int(content)
                        if existing_pid != os.getpid() and not self._is_pid_alive(existing_pid):
                            try:
                                self.lock_file_path.unlink(missing_ok=True)
                            except Exception:
                                pass
                except Exception:
                    pass

            self.file_handle = open(self.lock_file_path, "a+")
            if os.name == "nt":
                import msvcrt
                try:
                    self.file_handle.seek(0)
                    msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_NBLCK, 1)
                    self.file_handle.seek(0)
                    self.file_handle.truncate()
                    self.file_handle.write(str(os.getpid()))
                    self.file_handle.flush()
                    return True
                except (IOError, OSError, PermissionError):
                    return False
            else:
                import fcntl
                try:
                    fcntl.flock(self.file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.file_handle.seek(0)
                    self.file_handle.truncate()
                    self.file_handle.write(str(os.getpid()))
                    self.file_handle.flush()
                    return True
                except (IOError, OSError):
                    return False
        except Exception:
            return True

    def release(self):
        if self.file_handle:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.file_handle.seek(0)
                    msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file_handle, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self.file_handle.close()
            except Exception:
                pass

_mcp_lock = SingleInstanceLock(Path(os.getenv("SYNAP_STATE_DIR", str(Path(__file__).parent.parent / "state"))) / "mcp_server.lock")
if not _mcp_lock.acquire():
    print("mcp_server.py instance is already running or initializing. Exiting.")
    sys.exit(0)

import atexit
atexit.register(lambda: _mcp_lock.release())

# Import existing systems
from memory.store import MemoryStore
from memory.memory_sharp_integration import TurnAwareMemorySystem
from memory.weaver import Weaver
from memory.voice_integration import VoiceMemoryIntegration
from agent.tools import list_tools as get_registry_tools, get_tool

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("Gateway")

# â”€â”€ MCP Socket Client â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class MCPClient:
    def __init__(self, host="127.0.0.1", port=11438):
        self.host = host
        self.port = port
    
    def call(self, action: str, params: dict) -> dict:
        payload = json.dumps({"action": action, "params": params}) + "\n"
        try:
            with socket.create_connection((self.host, self.port), timeout=60) as s:
                s.sendall(payload.encode("utf-8"))
                buf = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    if b"\n" in buf:
                        break
                return json.loads(buf.decode("utf-8").strip())
        except Exception as e:
            logger.error(f"MCP call failed [{action}]: {e}")
            return {"success": False, "error": str(e)}

# â”€â”€ Gateway â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class Gateway:
    def __init__(self):
        self.mcp = MCPClient()
        
        # Initialize local systems
        self.store = MemoryStore()
        self.memory = TurnAwareMemorySystem(store=self.store)
        self.weaver = Weaver(store=self.store, memory_system=self.memory)
        self.weaver.start(interval=3.0)
        
        # Voice (optional)
        self.voice = None
        try:
            self.voice = VoiceMemoryIntegration(self.memory)
            logger.info("âœ… Voice system ready")
        except Exception as e:
            logger.warning(f"Voice unavailable: {e}")
        
        # WebSocket clients
        self.ws_clients = set()
        
        # Out-of-band pending confirmations for critical tier actions
        self.pending_confirmations: Dict[str, dict] = {}
        self.confirmations_lock = Lock()
        
        # HTTP app
        self.app = Flask(__name__)
        CORS(self.app)
        self._setup_routes()
        
        logger.info("ðŸšª Gateway initialized")
    
    def _setup_routes(self):
        # â”€â”€ MCP JSON-RPC ENDPOINT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        @self.app.route("/mcp", methods=["POST"])
        def mcp_rpc():
            """MCP JSON-RPC 2.0 endpoint for tool discovery and execution."""
            
            # â”€â”€ VALIDATE CONTENT TYPE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if request.content_type != "application/json":
                logger.warning(f"MCP: Invalid Content-Type: {request.content_type}")
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": "Content-Type must be application/json"
                    }
                }), 415

            # â”€â”€ PARSE JSON â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            try:
                data = request.get_json(force=True, silent=False)
                if not isinstance(data, dict):
                    raise ValueError("Request body must be a JSON object")
            except Exception as e:
                logger.error(f"MCP: JSON parse error: {e}")
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {str(e)}"
                    }
                }), 400

            request_id = data.get("id")
            method = data.get("method")
            params = data.get("params") or {}

            # â”€â”€ VALIDATE METHOD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if not method:
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32600,
                        "message": "Invalid Request: missing 'method'"
                    }
                }), 400

            # â”€â”€ MCP HANDSHAKE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if method == "initialize":
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": f"{os.getenv('AGENT_NAME', 'Synap-Forge')} MCP Gateway",
                            "version": "1.0.0"
                        }
                    }
                })

            # â”€â”€ MCP INITIALIZED NOTIFICATION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if method == "notifications/initialized":
                return Response(status=204)

            TOOLS = {
                "adb_devices": {
                    "description": "List connected Android devices",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                "adb_install": {
                    "description": "Install an APK on an Android device",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path to APK file"}
                        },
                        "required": ["path"]
                    }
                },
                "adb_shell": {
                    "description": "Execute a shell command on an Android device",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "Shell command to execute"}
                        },
                        "required": ["command"]
                    }
                },
                "gradle_build": {
                    "description": "Build an Android project using Gradle",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string", "default": "assembleDebug"}
                        }
                    }
                },
                "git_commit": {
                    "description": "Commit repository changes",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string", "description": "Commit message"}
                        },
                        "required": ["message"]
                    }
                },
                "git_push": {
                    "description": "Push repository changes",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "remote": {"type": "string", "description": "The Git remote to push to"},
                            "branch": {"type": "string", "description": "The Git branch to push"},
                            "repo_path": {"type": "string", "description": "Canonical root of the repository (optional)"}
                        },
                        "required": ["remote", "branch"]
                    }
                },
                "search_memory": {
                    "description": "Search memory for relevant information",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "limit": {"type": "integer", "default": 5}
                        },
                        "required": ["query"]
                    }
                },
                "ingest_memory": {
                    "description": "Store information in memory",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "Content to store"}
                        },
                        "required": ["content"]
                    }
                },
                "search_code": {
                    "description": "Search source code database for query matching terms",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Code search query"},
                            "limit": {"type": "integer", "default": 5}
                        },
                        "required": ["query"]
                    }
                },
                "knowledge_stats": {
                    "description": "Get knowledge base index and document statistics",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                "smart_fix": {
                    "description": "Analyze an error message and retrieve suggested smart fix solution",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "error": {"type": "string", "description": "Error trace or message to analyze"}
                        },
                        "required": ["error"]
                    }
                },
                "get_memory_stats": {
                    "description": "Retrieve current memory fragment statistics and system state",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                "get_weaver_status": {
                    "description": "Retrieve active memory Weaver background status",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                "get_recent_patterns": {
                    "description": "Retrieve recently woven memory patterns",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "default": 5}
                        }
                    }
                },
                "read_file": {
                    "description": "Read a file from the filesystem",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Absolute path to the file"}
                        },
                        "required": ["file_path"]
                    }
                },
                "list_directory": {
                    "description": "List the contents of a directory",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "directory_path": {"type": "string", "description": "Absolute path to the directory"}
                        },
                        "required": ["directory_path"]
                    }
                },
                "write_file": {
                    "description": "Write content to a file on the filesystem",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Target file path"},
                            "content": {"type": "string", "description": "File content"}
                        },
                        "required": ["file_path", "content"]
                    }
                },
                "voice_listen": {
                    "description": "Listen and transcribe audio input",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "duration": {"type": "number", "description": "Duration in seconds"}
                        }
                    }
                },
                "voice_speak": {
                    "description": "Synthesize speech from text",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Text to synthesize"}
                        },
                        "required": ["text"]
                    }
                },
                "check_port": {
                    "description": "Check network port reachability",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "host": {"type": "string", "description": "Target host"},
                            "port": {"type": "integer", "description": "Target port"}
                        },
                        "required": ["port"]
                    }
                }
            }

            if method == "tools/list":
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {"name": name, **meta}
                            for name, meta in TOOLS.items()
                        ]
                    }
                })

            if method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments") or {}

                if not name:
                    return jsonify({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32602, "message": "Missing tool name"}
                    }), 400

                if name not in TOOLS:
                    return jsonify({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": f"Unknown tool: {name}"}
                    }), 404

                # â”€â”€ AUTHORIZE ACTION (JSON-RPC) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                authorized, err_msg, extra_data = self._authorize_action(name, arguments, dict(request.headers))
                if not authorized:
                    resp_data = {
                        "success": False,
                        "status": "pending_approval" if extra_data.get("requires_approval") else "failed",
                        "error": err_msg
                    }
                    if extra_data:
                        resp_data.update(extra_data)
                    return jsonify({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(resp_data)}],
                            "isError": True
                        }
                    })

                result = self.execute_action(name, arguments)
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result)}],
                        "isError": not result.get("success", False)
                    }
                })

            # â”€â”€ UNKNOWN METHOD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }), 400

        # â”€â”€ API ROUTES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        @self.app.route("/api/tools", methods=["GET"])
        def list_tools():
            """List all available tools from registry"""
            registry = get_registry_tools()
            tools = []
            for name, tool in registry.items():
                if not tool.enabled:
                    continue
                tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "schema": tool.schema,
                    "required_params": tool.required_params,
                    "policy": tool.policy
                })
            return jsonify({
                "tools": tools,
                "count": len(tools),
                "timestamp": datetime.now().isoformat()
            })

        @self.app.route("/api/<action>", methods=["POST"])
        def handle_action(action):
            """Handle API action"""
            data = request.get_json() or {}
            params = data.get("params", {})
            request_id = data.get("id", str(uuid.uuid4()))
            
            headers = dict(request.headers) if request else {}
            authorized, err_msg, extra_data = self._authorize_action(action, params, headers)
            if not authorized:
                resp_payload = {
                    "id": request_id,
                    "success": False,
                    "status": "pending_approval" if extra_data.get("requires_approval") else "failed",
                    "error": err_msg
                }
                if extra_data:
                    resp_payload.update(extra_data)
                return jsonify(resp_payload), 403

            result = self.execute_action(action, params)
            result["id"] = request_id
            return jsonify(result)
        
        # â”€â”€ OUT-OF-BAND CRITICAL ACTION CONFIRMATION ENDPOINTS â”€â”€
        @self.app.route("/api/confirmations", methods=["GET"])
        def list_confirmations():
            """List pending critical action confirmation requests requiring out-of-band human approval."""
            headers = dict(request.headers) if request else {}
            authorized, err_msg = self._authorize_approval_operator(headers)
            if not authorized:
                return jsonify({"success": False, "error": err_msg}), 403

            with self.confirmations_lock:
                now = time.time()
                expired_keys = [k for k, v in self.pending_confirmations.items() if v.get("expires_at", 0) <= now]
                for k in expired_keys:
                    del self.pending_confirmations[k]

                pending = [copy.deepcopy(v) for v in self.pending_confirmations.values() if v.get("status") == "pending"]
            return jsonify({
                "success": True,
                "pending_confirmations": pending,
                "count": len(pending)
            })

        @self.app.route("/api/approve_confirmation", methods=["POST"])
        def approve_confirmation():
            """Human operator out-of-band approval endpoint for pending critical action requests."""
            headers = dict(request.headers) if request else {}
            authorized, err_msg = self._authorize_approval_operator(headers)
            if not authorized:
                return jsonify({"success": False, "error": err_msg}), 403

            data = request.get_json() or {}
            approval_id = data.get("approval_id", "")
            
            # Strict explicit Boolean type check
            if "approved" not in data or not isinstance(data.get("approved"), bool):
                return jsonify({
                    "success": False,
                    "error": "Field 'approved' is required and must be an explicit boolean (true or false)"
                }), 400

            approved = data.get("approved")

            with self.confirmations_lock:
                if not approval_id or approval_id not in self.pending_confirmations:
                    return jsonify({"success": False, "error": "Pending confirmation request not found"}), 404

                req = self.pending_confirmations[approval_id]

                # ðŸš« ONE-WAY STATE GUARD: Only pending requests can be processed. Prevent state re-processing / double approval.
                if req.get("status") != "pending":
                    logger.warning(f"[AUTH DENIED] Request {approval_id} has already been processed: status='{req.get('status')}'")
                    return jsonify({
                        "success": False,
                        "error": "Approval request cannot be re-processed or has already been processed."
                    }), 403

                if req.get("expires_at", 0) <= time.time():
                    del self.pending_confirmations[approval_id]
                    return jsonify({"success": False, "error": "Pending confirmation request has expired"}), 410

                if approved:
                    approval_token = f"tok_{secrets.token_hex(16)}"
                    req["status"] = "approved"
                    req["approval_token"] = approval_token
                    logger.info(f"âœ… [CONSENT APPROVED] Out-of-band approval granted for action '{req['action']}' (ID: {approval_id})")
                    return jsonify({
                        "success": True,
                        "approval_id": approval_id,
                        "action": req["action"],
                        "approval_token": approval_token,
                        "expires_at": req["expires_at"],
                        "message": "Approval granted. Execute critical action using params: {'approval_token': '<token>'}"
                    })
                else:
                    req["status"] = "rejected"
                    del self.pending_confirmations[approval_id]
                    logger.info(f"ðŸš« [CONSENT REJECTED] Out-of-band approval rejected for action '{req['action']}' (ID: {approval_id})")
                    return jsonify({
                        "success": True,
                        "approval_id": approval_id,
                        "message": "Pending confirmation request rejected and removed."
                    })

        @self.app.route("/api/chat", methods=["POST"])
        def chat():
            """Direct chat endpoint"""
            data = request.get_json()
            message = data.get("message", "")
            session_id = data.get("session_id", "default")
            
            result = self.memory.recall_with_turns(message, limit=5)
            context = result.get("context", "")
            patterns = self.weaver.get_recent_patterns(3)
            
            return jsonify({
                "success": True,
                "response": {
                    "message": message,
                    "context": context,
                    "patterns": patterns,
                    "session": session_id,
                    "timestamp": datetime.now().isoformat()
                }
            })
        
        @self.app.route("/health", methods=["GET"])
        def health():
            """Health check"""
            return jsonify({
                "status": "healthy",
                "gateway": "running",
                "mcp": self._check_mcp(),
                "memory": self._check_memory(),
                "weaver": self.weaver.running,
                "timestamp": datetime.now().isoformat()
            })

        @self.app.route("/tts", methods=["POST"])
        def tts_route():
            try:
                data = request.json
                if not data or "text" not in data:
                    return {"error": "Missing text"}, 400
                text = data["text"].strip()
                if not text:
                    return {"error": "Empty text"}, 400
                if self.voice is None:
                    return {"error": "Voice not initialized"}, 503
                audio_data = self.voice.synthesize_wav(text)
                return Response(audio_data, mimetype="audio/wav")
            except Exception as e:
                logger.exception("TTS failed")
                return {"error": str(e)}, 500
    
    def _check_mcp(self) -> bool:
        """Check if MCP server is reachable"""
        try:
            result = self.mcp.call("check_port", {"host": "127.0.0.1", "port": 11438})
            return result.get("open", False)
        except:
            return False
    
    def _check_memory(self) -> bool:
        """Check if memory system is working"""
        try:
            stats = self.memory.get_status()
            return stats.get("memory_stats", {}).get("total_fragments", 0) > 0
        except:
            return False
    
    ACTION_RISK_TIERS = {
        "read": {
            "health", "adb_devices", "adb_list_devices", "search_memory",
            "get_memory_stats", "get_weaver_status", "get_recent_patterns",
            "search_code", "knowledge_stats", "read_file", "list_directory",
            "list_files", "check_port"
        },
        "limited": {
            "gradle_build", "voice_listen", "voice_speak", "smart_fix",
            "write_file", "add_code"
        },
        "privileged": {
            "adb_shell", "adb_install", "git_commit", "ingest_memory"
        },
        "critical": {
            "git_push"
        }
    }

    def _authorize_approval_operator(self, headers: dict) -> Tuple[bool, str]:
        """Operator privilege boundary for critical action out-of-band approvals."""
        headers = headers or {}
        admin_key = os.getenv("MCP_ADMIN_KEY", os.getenv("MCP_APPROVAL_KEY", os.getenv("MCP_API_KEY", os.getenv("SYNAP_API_KEY"))))

        provided_token = None
        auth_header = headers.get("Authorization") or headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            provided_token = auth_header[7:].strip()

        if admin_key:
            if not provided_token or not secrets.compare_digest(provided_token, admin_key):
                logger.warning("[AUTH DENIED] Operator approval endpoint called with invalid or missing Bearer token.")
                return False, "Unauthorized: invalid or missing operator approval credential"
            return True, "OK"
        else:
            logger.warning("[AUTH DENIED] Operator approval rejected because MCP_ADMIN_KEY or MCP_API_KEY is not configured on the server.")
            return False, "Unauthorized: operator approval requires MCP_ADMIN_KEY or MCP_API_KEY configured on the server"

    def _authorize_action(self, action: str, params: dict, headers: dict = None) -> Tuple[bool, str, dict]:
        """Pre-dispatch authorization pipeline (Default Deny). Returns (authorized, err_msg, extra_data)."""
        headers = headers or {}
        
        # 1. Action Tier Resolution (Default Deny)
        tier = None
        for t, actions in self.ACTION_RISK_TIERS.items():
            if action in actions:
                tier = t
                break
        
        if tier is None:
            logger.warning(f"[AUTH DENIED] Unrecognized action '{action}' blocked by default-deny policy.")
            return False, f"Unauthorized: action '{action}' is not in allowed action registry", {}

        # 2. Mode-Based Constraint ("off_clock" blocks privileged & critical)
        system_mode = os.getenv("SYNAP_SYSTEM_MODE", os.getenv("CLOCK_MODE", "on_clock")).lower()
        if system_mode in ["off_clock", "offclock", "offline"]:
            if tier in ["privileged", "critical"]:
                logger.warning(f"[AUTH DENIED] Action '{action}' ({tier}) blocked in off-clock mode.")
                return False, f"Unauthorized: action '{action}' is disabled during off-clock mode", {}

        # 3. Authentication & Bearer Token Verification (Unified: AUTH_TOKEN -> MCP_API_KEY -> SYNAP_API_KEY)
        expected_token = os.getenv("AUTH_TOKEN") or os.getenv("MCP_API_KEY") or os.getenv("SYNAP_API_KEY")
        
        provided_token = None
        auth_header = headers.get("Authorization") or headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            provided_token = auth_header[7:].strip()

        if expected_token:
            if not provided_token or not secrets.compare_digest(provided_token, expected_token):
                logger.warning(f"[AUTH DENIED] Invalid or missing Bearer token for action '{action}'.")
                return False, "Unauthorized: invalid or missing authentication token", {}
        else:
            logger.warning(f"[AUTH DENIED] Action '{action}' ({tier}) blocked because AUTH_TOKEN / MCP_API_KEY / SYNAP_API_KEY is not configured on the server.")
            return False, f"Unauthorized: server authentication token is not configured (AUTH_TOKEN / MCP_API_KEY / SYNAP_API_KEY required)", {}

        # 4. Critical Tier Out-of-Band Interactive Consent Barrier
        if tier == "critical":
            approval_token = params.get("approval_token")
            params_clean = {k: v for k, v in params.items() if k != "approval_token"}

            valid_approval = False
            with self.confirmations_lock:
                if approval_token:
                    matching_id = None
                    for req_id, req in list(self.pending_confirmations.items()):
                        if req.get("status") == "approved" and req.get("approval_token") == approval_token:
                            if req.get("expires_at", 0) > time.time():
                                if req.get("action") == action and req.get("params") == params_clean:
                                    valid_approval = True
                                    matching_id = req_id
                                    break
                    if valid_approval and matching_id:
                        # Single-use atomic consumption under lock
                        del self.pending_confirmations[matching_id]
                        logger.info(f"ðŸ”’ [CONSENT VERIFIED] Critical action '{action}' executed with valid out-of-band approval token.")
                    else:
                        logger.warning(f"[AUTH DENIED] Critical action '{action}' blocked: invalid, expired, or parameter-mismatched approval_token.")
                        return False, f"Unauthorized: invalid or expired out-of-band approval_token for action '{action}'", {}

                if not valid_approval:
                    now = time.time()
                    for k in list(self.pending_confirmations.keys()):
                        if self.pending_confirmations[k].get("expires_at", 0) <= now:
                            del self.pending_confirmations[k]

                    approval_id = f"req_{secrets.token_hex(8)}"
                    self.pending_confirmations[approval_id] = {
                        "approval_id": approval_id,
                        "action": action,
                        "params": params_clean,
                        "created_at": now,
                        "expires_at": now + 300,  # 5-minute expiration window
                        "status": "pending",
                        "approval_token": None
                    }
                    logger.warning(f"[AUTH DENIED] Critical action '{action}' blocked: requires out-of-band approval. Request ID: {approval_id}")
                    return False, f"Unauthorized: critical action '{action}' requires out-of-band human approval. Confirmation pending with ID '{approval_id}'", {
                        "requires_approval": True,
                        "approval_id": approval_id,
                        "action": action
                    }

        return True, "OK", {}

    def execute_action(self, action: str, params: dict) -> dict:
        """Execute an action"""
        start = time.time()
        result = {"success": False, "result": None}
        
        try:
            # Local actions
            if action == "search_memory":
                result = self._search_memory(params)
            elif action == "get_memory_stats":
                result = self._get_memory_stats(params)
            elif action == "get_weaver_status":
                result = self._get_weaver_status(params)
            elif action == "get_recent_patterns":
                result = self._get_recent_patterns(params)
            elif action == "ingest_memory":
                result = self._ingest_memory(params)
            elif action == "read_file":
                result = self._read_file(params)
            elif action in ("list_directory", "list_files"):
                result = self._list_directory(params)
            elif action == "write_file":
                result = self._write_file(params)
            elif action == "check_port":
                result = self._check_port_action(params)
            elif action == "voice_listen":
                result = self._voice_listen(params)
            elif action == "voice_speak":
                result = self._voice_speak(params)
            elif action == "search_code":
                result = self._search_code(params)
            elif action == "knowledge_stats":
                result = self._knowledge_stats(params)
            elif action == "smart_fix":
                result = self._smart_fix(params)
            elif action in ("adb_devices", "adb_list_devices"):
                result = self._adb_devices(params)
            elif action == "adb_install":
                result = self._adb_install(params)
            elif action == "adb_shell":
                result = self._adb_shell(params)
            elif action == "gradle_build":
                result = self._gradle_build(params)
            elif action == "git_commit":
                result = self._git_commit(params)
            elif action == "git_push":
                result = self._git_push(params)
            # Forward to MCP
            else:
                result = self.mcp.call(action, params)
            
            if "status" in result:
                result["success"] = result["status"] in {"success", "succeeded"}
            else:
                result["success"] = (
                    "error" not in result
                    and result.get("success") is not False
                )
        except Exception as e:
            logger.error(f"Action failed [{action}]: {e}")
            result = {"success": False, "error": str(e)}
        
        result["_ms"] = round((time.time() - start) * 1000, 1)
        return result

    def _read_file(self, params: dict) -> dict:
        file_path = params.get("file_path") or params.get("path") or ""
        if not file_path:
            return {"error": "Missing file_path parameter", "status": "failed"}
        try:
            p = Path(file_path)
            if not p.exists():
                return {"error": f"File not found: {file_path}", "status": "failed"}
            if not p.is_file():
                return {"error": f"Path is not a file: {file_path}", "status": "failed"}
            content = p.read_text(encoding="utf-8", errors="replace")
            return {"status": "success", "file_path": str(p), "content": content}
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    def _list_directory(self, params: dict) -> dict:
        directory_path = params.get("directory_path") or params.get("path") or "."
        try:
            p = Path(directory_path)
            if not p.exists():
                return {"error": f"Directory not found: {directory_path}", "status": "failed"}
            if not p.is_dir():
                return {"error": f"Path is not a directory: {directory_path}", "status": "failed"}
            entries = []
            for child in p.iterdir():
                entries.append({
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else 0
                })
            return {"status": "success", "directory_path": str(p), "entries": entries}
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    def _write_file(self, params: dict) -> dict:
        file_path = params.get("file_path") or params.get("path") or ""
        content = params.get("content", "")
        if not file_path:
            return {"error": "Missing file_path parameter", "status": "failed"}
        try:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"status": "success", "file_path": str(p), "bytes_written": len(content)}
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    def _check_port_action(self, params: dict) -> dict:
        target_host = params.get("host") or os.getenv("MCP_HOST", "127.0.0.1")
        target_port = params.get("port")
        if not target_port:
            return {"error": "Missing port parameter", "status": "failed"}
        try:
            port_num = int(target_port)
            with socket.create_connection((target_host, port_num), timeout=2):
                return {"status": "success", "open": True, "host": target_host, "port": port_num}
        except Exception as e:
            return {"status": "success", "open": False, "host": target_host, "port": target_port, "error": str(e)}

    def _search_memory(self, params: dict) -> dict:
        query = params.get("query", "")
        limit = params.get("limit", 5)
        result = self.memory.recall_with_turns(query, limit=limit)
        return {"result": result}
    
    def _get_memory_stats(self, params: dict) -> dict:
        status = self.memory.get_status()
        return {"result": status.get("memory_stats", {})}
    
    def _get_weaver_status(self, params: dict) -> dict:
        return {"result": self.weaver.get_status()}
    
    def _get_recent_patterns(self, params: dict) -> dict:
        limit = params.get("limit", 5)
        return {"result": self.weaver.get_recent_patterns(limit)}
    
    def _ingest_memory(self, params: dict) -> dict:
        content = params.get("content", "")
        if not content:
            return {"error": "Missing content"}
        self.store.add_memory(content, memory_type="interaction")
        return {"result": {"stored": True, "content": content[:50] + "..."}}
    
    def _voice_listen(self, params: dict) -> dict:
        if not self.voice or not getattr(self.voice, 'voice', None):
            return {"status": "failed", "error": "Voice system not initialized"}
        whisper = getattr(self.voice.voice, 'whisper_model', None)
        if whisper is None:
            return {"status": "failed", "error": "STT unavailable (Faster-Whisper model not loaded)"}
        duration = float(params.get("duration", 5.0))
        try:
            captured_text = []
            def _on_captured(t):
                captured_text.append(t)
            self.voice.voice.listen(_on_captured, duration=duration)
            text = " ".join(captured_text).strip()
            return {"status": "success", "text": text, "captured": bool(text)}
        except Exception as e:
            return {"status": "failed", "error": f"Voice listen execution failed: {str(e)}"}
    
    def _voice_speak(self, params: dict) -> dict:
        if not self.voice or not getattr(self.voice, 'voice', None):
            return {"status": "failed", "error": "Voice system not initialized"}
        text = params.get("text", "")
        if not text:
            return {"status": "failed", "error": "Missing required 'text' parameter"}
        try:
            if getattr(self.voice.voice, 'tts_pipeline', None) is not None:
                self.voice.voice.speak(text)
                return {"status": "success", "message": f"Spoke: {text[:50]}...", "text": text}
            else:
                return {"status": "success", "message": f"Voice acknowledge: {text[:50]}...", "text": text}
        except Exception as e:
            return {"status": "failed", "error": f"Voice speak execution failed: {str(e)}"}
    
    def _search_code(self, params: dict) -> dict:
        query = params.get("query", "")
        limit = params.get("limit", 5)
        try:
            from code_database import search_code
            results = search_code(query, limit=limit)
            return {"result": results}
        except Exception as e:
            return {"error": str(e)}
    
    def _knowledge_stats(self, params: dict) -> dict:
        try:
            from knowledge_db import get_statistics
            stats = get_statistics()
            return {"result": stats}
        except Exception as e:
            return {"error": str(e)}
    
    def _smart_fix(self, params: dict) -> dict:
        error_message = params.get("error", "")
        if not error_message:
            return {"error": "Missing error message"}
        try:
            from knowledge_db import get_smart_fix
            fix = get_smart_fix(error_message)
            return {"result": fix}
        except Exception as e:
            return {"error": str(e)}

    # â”€â”€ Android / ADB Handlers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _adb_devices(self, params: dict) -> dict:
        import subprocess
        import re
        try:
            result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=5)
            devices = []
            for line in result.stdout.splitlines():
                # Skip header lines
                if "List of devices attached" in line or not line.strip():
                    continue
                # Match: device_id followed by whitespace and status
                match = re.match(r'^(\S+)\s+(device|offline|unauthorized)', line.strip())
                if match:
                    devices.append({
                        "id": match.group(1),
                        "status": match.group(2)
                    })
            
            if devices:
                return {
                    "devices": devices,
                    "count": len(devices),
                    "status": "success",
                    "message": f"Found {len(devices)} device(s)"
                }
            else:
                return {
                    "devices": [],
                    "count": 0,
                    "status": "success",
                    "message": "No real ADB devices found"
                }
        except Exception as e:
            return {
                "devices": [],
                "count": 0,
                "status": "failed",
                "error": str(e),
                "message": f"ADB devices query failed: {str(e)}"
            }

    def _adb_install(self, params: dict) -> dict:
        path = params.get("path", "")
        if not path:
            return {"error": "Missing path parameter", "status": "failed"}
        
        import subprocess
        try:
            result = subprocess.run(['adb', 'install', path], capture_output=True, text=True, timeout=30)
            if 'Success' in result.stdout:
                return {
                    "path": path,
                    "status": "success",
                    "message": f"APK installed successfully from {path}"
                }
            else:
                return {
                    "path": path,
                    "status": "failed",
                    "error": result.stderr or "Installation failed"
                }
        except Exception as e:
            return {
                "path": path,
                "status": "failed",
                "error": str(e)
            }

    def _adb_shell(self, params: dict) -> dict:
        command = params.get("command", "")
        if not command:
            return {"error": "Missing command parameter", "status": "failed"}
        
        import subprocess
        try:
            result = subprocess.run(['adb', 'shell', command], capture_output=True, text=True, timeout=10)
            return {
                "command": command,
                "output": result.stdout or result.stderr,
                "status": "success"
            }
        except Exception as e:
            return {
                "command": command,
                "error": str(e),
                "status": "failed"
            }

    def _gradle_build(self, params: dict) -> dict:
        task = params.get("task", "assembleDebug")
        import subprocess
        import random
        try:
            result = subprocess.run(['./gradlew', task], capture_output=True, text=True, timeout=120, cwd='.')
            if result.returncode == 0:
                return {
                    "task": task,
                    "status": "success",
                    "output": result.stdout[-500:],
                    "message": f"Build completed successfully: {task}"
                }
            else:
                return {
                    "task": task,
                    "status": "failed",
                    "error": result.stderr[-500:],
                    "message": "Build failed"
                }
        except Exception as e:
            return {
                "task": task,
                "status": "failed",
                "error": str(e),
                "message": f"Gradle build failed: {str(e)}"
            }

    ALLOWED_REPOSITORIES = {
        "mastercontrols": {
            "path": os.path.realpath(r"C:\Users\bc_ri\AppData\Roaming\applications\MASTERCONTROLS"),
            "allowed_remotes": {"mc_remote"},
            "allowed_remote_urls": {
                "https://github.com/aaroncrosswell74-source/MASTERCONTROLS.git"
            },
            "allowed_branches": {"feature/ktor-transport-adapter"},
            "allow_push": True
        }
    }

    def _validate_repo_path(self, req_path: str = None) -> Tuple[bool, str, Optional[str], Optional[dict]]:
        """
        Validates path against canonical root and verifies Git work tree presence.
        """
        cfg = self.ALLOWED_REPOSITORIES["mastercontrols"]
        approved_root = os.path.normcase(os.path.realpath(cfg["path"]))
        
        try:
            target_real = os.path.normcase(os.path.realpath(req_path or cfg["path"]))
        except (OSError, TypeError, ValueError) as e:
            return False, f"Invalid repository path: {e}", None, None

        if target_real != approved_root:
            return False, "Repository path must equal the approved canonical root", None, None

        if not os.path.isdir(target_real):
            return False, "Approved repository directory does not exist", None, None

        import subprocess
        try:
            inside = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, timeout=5, cwd=approved_root
            )
            top = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=5, cwd=approved_root
            )
            
            if inside.returncode != 0 or inside.stdout.strip() != "true" or top.returncode != 0:
                return False, "Git work tree verification failed", None, None
            
            actual_root = os.path.normcase(os.path.realpath(top.stdout.strip()))
            if actual_root != approved_root:
                return False, "Git top-level differs from approved root", None, None
                
        except Exception as e:
            return False, f"Git root verification failed: {e}", None, None

        return True, "OK", approved_root, cfg

    def _git_commit(self, params: dict) -> dict:
        message = params.get("message", "")
        if not message:
            return {"error": "Missing message parameter", "status": "error"}

        repo_path = params.get("repo_path") or params.get("cwd")
        is_valid, err_msg, target_dir, repo_cfg = self._validate_repo_path(repo_path)
        if not is_valid:
            return {"error": err_msg, "status": "error"}

        import subprocess
        try:
            result = subprocess.run(['git', 'commit', '-m', message], capture_output=True, text=True, timeout=15, cwd=target_dir)
            if result.returncode == 0:
                hash_result = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5, cwd=target_dir)
                commit_hash = hash_result.stdout.strip()[:8] if hash_result.returncode == 0 else "unknown"
                return {
                    "message": message,
                    "commit_hash": commit_hash,
                    "status": "success",
                    "repo_path": target_dir,
                    "output": result.stdout
                }
            else:
                return {
                    "message": message,
                    "status": "error",
                    "error": result.stderr or result.stdout or "Git commit failed",
                    "repo_path": target_dir
                }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "message": f"Git commit failed: {str(e)}",
                "repo_path": target_dir
            }

    def _git_push(self, params: dict) -> dict:
        repo_path = params.get("repo_path") or params.get("cwd")
        is_valid, err_msg, target_dir, repo_cfg = self._validate_repo_path(repo_path)
        if not is_valid:
            return {"error": err_msg, "status": "error"}

        if not repo_cfg.get("allow_push", False):
            return {"error": f"Push operations are disabled for repository at '{target_dir}'", "status": "error"}

        remote = params.get("remote")
        branch = params.get("branch")
        if not isinstance(remote, str) or not remote:
            return {"error": "Explicit remote required", "status": "error"}
        if not isinstance(branch, str) or not branch:
            return {"error": "Explicit branch required", "status": "error"}

        allowed_remotes = repo_cfg.get("allowed_remotes", set())
        allowed_branches = repo_cfg.get("allowed_branches", set())
        allowed_remote_urls = repo_cfg.get("allowed_remote_urls", set())

        if remote not in allowed_remotes:
            return {"error": f"Unauthorized remote '{remote}'. Allowed remotes: {allowed_remotes}", "status": "error"}

        if branch not in allowed_branches:
            return {"error": f"Unauthorized branch '{branch}'. Allowed branches: {allowed_branches}", "status": "error"}

        import subprocess
        # Validate configured remote URL against allowed_remote_urls
        try:
            url_res = subprocess.run(['git', 'remote', 'get-url', remote], capture_output=True, text=True, timeout=5, cwd=target_dir)
            if url_res.returncode != 0:
                return {"error": f"Failed to retrieve URL for remote '{remote}': {url_res.stderr.strip()}", "status": "error"}
            
            configured_url = url_res.stdout.strip()
            if configured_url not in allowed_remote_urls:
                logger.warning(f"[REMOTE URL VIOLATION] Remote '{remote}' URL '{configured_url}' not in allowlist: {allowed_remote_urls}")
                return {"error": f"Unauthorized remote URL '{configured_url}' for remote '{remote}'", "status": "error"}
        except Exception as e:
            return {"error": f"Error validating remote URL: {str(e)}", "status": "error"}

        try:
            result = subprocess.run(['git', 'push', remote, branch], capture_output=True, text=True, timeout=30, cwd=target_dir)
            if result.returncode == 0:
                return {
                    "status": "success",
                    "output": result.stdout,
                    "remote": remote,
                    "branch": branch,
                    "repo_path": target_dir,
                    "message": f"Pushed to {remote}/{branch} successfully"
                }
            else:
                return {
                    "status": "error",
                    "error": result.stderr or result.stdout or "Push failed",
                    "remote": remote,
                    "branch": branch,
                    "repo_path": target_dir,
                    "message": f"Push to {remote}/{branch} failed with non-zero exit code"
                }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "remote": remote,
                "branch": branch,
                "repo_path": target_dir,
                "message": f"Git push failed with exception: {str(e)}"
            }

    def start_http(self, port: int = 11440):
        host = os.getenv("MCP_HOST", "127.0.0.1")
        logger.info(f"ðŸŒ HTTP Gateway running on {host}:{port}")
        self.app.run(host=host, port=port, debug=False, threaded=True)
    
    async def start_websocket(self, port: int = 11441):
        if not WEBSOCKET_AVAILABLE:
            logger.warning("WebSocket not available - install websockets")
            return
        
        host = os.getenv("MCP_HOST", "127.0.0.1")
        
        async def handler(websocket, path=None):
            self.ws_clients.add(websocket)
            
            # Extract HTTP handshake request headers from WebSocket connection
            ws_headers = {}
            if hasattr(websocket, "request_headers") and websocket.request_headers:
                try:
                    ws_headers = {k: v for k, v in websocket.request_headers.items()}
                except Exception as e:
                    logger.debug(f"Failed to extract WebSocket headers: {e}")

            try:
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        action = data.get("action", "")
                        params = data.get("params", {})
                        req_id = data.get("id", str(uuid.uuid4()))
                        
                        authorized, err_msg, extra_data = self._authorize_action(action, params, ws_headers)
                        if not authorized:
                            resp_ws = {
                                "id": req_id,
                                "success": False,
                                "status": "pending_approval" if extra_data.get("requires_approval") else "failed",
                                "error": err_msg
                            }
                            if extra_data:
                                resp_ws.update(extra_data)
                            await websocket.send(json.dumps(resp_ws))
                            continue

                        result = self.execute_action(action, params)
                        result["id"] = req_id
                        
                        await websocket.send(json.dumps(result))
                    except json.JSONDecodeError:
                        await websocket.send(json.dumps({
                            "id": "error",
                            "success": False,
                            "error": "Invalid JSON"
                        }))
                    except Exception as e:
                        logger.error(f"Error handling WebSocket message: {e}")
                        await websocket.send(json.dumps({
                            "id": "error",
                            "success": False,
                            "error": str(e)
                        }))
            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as e:
                logger.error(f"WebSocket connection error: {e}")
            finally:
                self.ws_clients.discard(websocket)
        
        async def ws_server():
            async with serve(handler, host, port):
                logger.info(f"ðŸ”Œ WebSocket Gateway running on {host}:{port}")
                await asyncio.Future()
        
        await ws_server()

def main():
    import sys
    import threading
    
    gateway = Gateway()
    
    http_thread = threading.Thread(
        target=gateway.start_http,
        args=(11440,),
        daemon=True
    )
    http_thread.start()
    
    try:
        asyncio.run(gateway.start_websocket(11441))
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    main()